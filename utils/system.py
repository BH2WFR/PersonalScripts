"""Operating-system integration, privilege, and permission helpers."""

import ctypes
import importlib
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable

from .ansi import *


class System:
    @staticmethod
    def get_arch() -> str:
        """Return the normalized machine architecture."""
        machine = platform.machine().lower()
        if machine in ("x86_64", "amd64"):
            return "amd64"
        if machine in ("x86", "i386", "i686"):
            return "386"
        if machine in ("arm64", "aarch64"):
            return "arm64"
        if machine.startswith("arm"):
            return "arm"
        return machine

    @staticmethod
    def get_computer_name() -> str:
        """Return the computer hostname."""
        return socket.gethostname()

    @staticmethod
    def get_os_name() -> str:
        """Return a human-readable operating-system name and version."""
        if sys.platform == "darwin":
            version = platform.mac_ver()[0]
            return f"macOS {version}" if version else "macOS"
        if sys.platform == "linux":
            return f"Linux ({platform.release()})"
        if sys.platform == "win32":
            edition = platform.win32_edition()
            base = f"Windows {platform.release()} {platform.version()}"
            return f"{base} {edition}" if edition else base
        return sys.platform

    @staticmethod
    def is_headless() -> bool:
        """Return True if the environment likely has no GUI/display available."""
        if sys.platform == "darwin":
            return False
        if sys.platform != "win32":
            return not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
        return False

    @staticmethod
    def open_browser_safe(url: str) -> None:
        """Open *url* in the default browser, silently skip on headless systems."""
        if System.is_headless():
            return
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    @staticmethod
    def enable_dpi_awareness() -> None:
        """Enable per-monitor DPI awareness on Windows (no-op on other platforms)."""
        if sys.platform != "win32":
            return

        user32 = ctypes.windll.user32
        # Windows 10+ recommended: Per Monitor V2
        try:
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
            if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
                return
        except Exception:
            pass

        # Win8.1 fallback
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            return
        except Exception:
            pass

        # Older systems fallback
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

    @staticmethod
    def is_elevated() -> bool:
        """Check if the current process has administrator/root privileges.

        Returns True on Windows (admin), macOS/Linux (root), or if detection fails.
        """
        if sys.platform == "win32":
            try:
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception:
                return False
        else:
            try:
                return os.geteuid() == 0
            except AttributeError:
                return False

    @staticmethod
    def restart_elevated() -> None:
        """Re-execute the current script with administrator/root privileges.

        **Must be called at the very beginning of the program**, before any
        output is written to stdout.  On Windows the Win32 API fallback spawns
        a fresh console window that cannot render ANSI escape sequences; any
        prior output will appear garbled or be lost.

        If already elevated, returns immediately.  Does **not** return when
        elevation succeeds — the current process is replaced via ``os.execv``
        or ``sys.exit(0)``.

        Elevation order
            **Linux / macOS** — ``sudo`` only.
            **Windows** — ``gsudo`` → ``sudo`` → Win32 ``ShellExecuteW``
            (last resort; spawns a separate Python console window with no ANSI
            support).  All in-place helpers are called via ``subprocess.run``
            instead of ``os.execv`` to avoid stdin contention.

        Once a helper starts, the parent exits with the child's status instead
        of trying another helper.
        """
        if System.is_elevated():
            return

        script = os.path.abspath(sys.argv[0])
        args = sys.argv[1:]

        if sys.platform == "win32":
            # 1) gsudo — in-place elevation, preserves ANSI escapes.
            # 2) sudo  — same-terminal elevation fallback.
            # Use subprocess.run instead of os.execv: scoop's sudo does not
            # properly detach stdin, causing two processes to compete for input
            # and producing doubled keystrokes / cursor glitches.
            failures: list[str] = []
            for name in ("gsudo", "sudo"):
                executable = shutil.which(name)
                if executable is None:
                    failures.append(f"{name}: not found in PATH")
                    continue
                try:
                    result = subprocess.run(
                        [executable, sys.executable, script, *args],
                        check=False,
                    )
                except OSError as exc:
                    failures.append(f"{name}: failed to start ({exc})")
                    continue
                raise SystemExit(result.returncode)

            # 3) ShellExecuteW — last resort.  Spawns a fresh console window;
            #    ANSI escape sequences are not carried over.
            sys.stdout.flush()
            print()
            params = subprocess.list2cmdline([script] + args)
            try:
                ret = ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", sys.executable, params, None, 1,
                )
            except OSError as exc:
                failures.append(f"Windows UAC: failed to start ({exc})")
            else:
                if ret > 32:
                    sys.exit(0)
                failures.append(f"Windows UAC: ShellExecuteW error {ret}")

            print(f"{FLRed}Elevation failed: {'; '.join(failures)}.{CRst}")
            print(
                f"{FLYellow}Run this script from an Administrator PowerShell "
                f"window and try again.{CRst}"
            )
            sys.exit(1)
        else:
            if shutil.which("sudo"):
                os.execv("/usr/bin/sudo", ["sudo", sys.executable, script] + args)
            print(f"{FLRed}Cannot elevate: sudo not found in PATH.{CRst}")
            sys.exit(1)

    @staticmethod
    def try_restart_elevated() -> bool:
        """Re-launch via a helper that waits for the child to finish.

        **Should be called as early as possible**, before significant output,
        though the in-place helpers (``gsudo`` / ``sudo``) preserve the
        terminal state and are more forgiving than the Win32 API fallback.

        Unlike :meth:`restart_elevated`, this does **not** fall back to
        ``ShellExecuteW`` spawning a new window and only returns when every
        helper is unavailable or fails with a non-zero exit code — the caller
        can then continue without privileges.

        If already elevated, returns ``True`` immediately so the caller can
        simply proceed.

        Elevation order
            **Linux / macOS** — ``sudo`` only.
            **Windows** — ``gsudo`` → ``sudo`` (both in-place).

        Raises ``SystemExit(0)`` when the child exits successfully.
        Returns ``False`` if no helper was found or every helper exited with a
        non-zero code — the caller should continue with reduced privileges.
        """
        if System.is_elevated():
            return True

        helpers: list[str] = (
            ["gsudo", "sudo"] if sys.platform == "win32" else ["sudo"]
        )
        script = os.path.abspath(sys.argv[0])
        args = sys.argv[1:]

        for name in helpers:
            exe = shutil.which(name)
            if exe is None:
                continue
            try:
                result = subprocess.run(
                    [exe, sys.executable, script] + args,
                    check=False,
                )
            except Exception:
                continue
            if result.returncode == 0:
                raise SystemExit(0)
            # Non-zero exit — try next helper.
        return False

    @staticmethod
    def open_with_default_app(path: str) -> None:
        """Open a file or directory with the OS default application."""
        abs_path = os.path.abspath(path)
        if sys.platform == "win32":
            os.startfile(abs_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", abs_path], check=False)
        else:
            subprocess.run(["xdg-open", abs_path], check=False)

    @staticmethod
    def notify(title: str, body: str) -> None:
        """Send a desktop notification (best-effort, silently fails)."""
        try:
            if sys.platform == "win32":
                try:
                    from win10toast import ToastNotifier
                    ToastNotifier().show_toast(title, body, duration=5, threaded=True)
                except ImportError:
                    pass
            elif sys.platform == "darwin":
                subprocess.run([
                    "osascript", "-e",
                    f'display notification "{body}" with title "{title}"',
                ], check=False, capture_output=True)
            else:
                subprocess.run(["notify-send", title, body], check=False, capture_output=True)
        except Exception:
            pass

    @staticmethod
    def check_macos_accessibility_permission(*, prompt: bool = False) -> bool:
        """Return whether this process has macOS Accessibility access.

        When prompt is true, macOS may show its native authorization prompt.
        Non-macOS platforms return True.
        """
        if sys.platform != "darwin":
            return True
        try:
            # These symbols are injected dynamically by PyObjC and are absent
            # from its static type stubs, so resolve them at runtime.
            application_services = importlib.import_module("ApplicationServices")
            is_trusted_with_options = getattr(
                application_services,
                "AXIsProcessTrustedWithOptions",
            )
            prompt_option = getattr(
                application_services,
                "kAXTrustedCheckOptionPrompt",
            )
            return bool(is_trusted_with_options({
                prompt_option: prompt,
            }))
        except (ImportError, AttributeError, OSError):
            try:
                framework = ctypes.CDLL(
                    "/System/Library/Frameworks/"
                    "ApplicationServices.framework/ApplicationServices"
                )
                framework.AXIsProcessTrusted.argtypes = []
                framework.AXIsProcessTrusted.restype = ctypes.c_bool
                return bool(framework.AXIsProcessTrusted())
            except (AttributeError, OSError):
                return False

    @staticmethod
    def check_macos_screen_recording_permission(
        *,
        request: bool = False,
    ) -> bool:
        """Return whether this process has macOS Screen Recording access.

        When request is true, macOS may show its native authorization prompt.
        Non-macOS platforms return True.
        """
        if sys.platform != "darwin":
            return True
        try:
            framework = ctypes.CDLL(
                "/System/Library/Frameworks/"
                "CoreGraphics.framework/CoreGraphics"
            )
            function_name = (
                "CGRequestScreenCaptureAccess"
                if request
                else "CGPreflightScreenCaptureAccess"
            )
            check = getattr(framework, function_name)
            check.argtypes = []
            check.restype = ctypes.c_bool
            return bool(check())
        except (AttributeError, OSError):
            return False

    @staticmethod
    def ensure_macos_permissions(
        *,
        accessibility: bool = False,
        screen_recording: bool = False,
        timeout_s: float = 60.0,
        prompt: bool = True,
    ) -> bool:
        """Ensure requested macOS TCC permissions are available.

        System prompts and settings panes still require explicit user approval.
        This method waits up to timeout_s for that approval. Non-macOS
        platforms return True.
        """
        if sys.platform != "darwin":
            return True

        accessibility_ok = (
            not accessibility
            or System.check_macos_accessibility_permission(prompt=prompt)
        )
        screen_recording_ok = (
            not screen_recording
            or System.check_macos_screen_recording_permission(request=prompt)
        )
        if accessibility_ok and screen_recording_ok:
            return True

        missing: list[str] = []
        if not accessibility_ok:
            missing.append("Accessibility (mouse/keyboard control)")
        if not screen_recording_ok:
            missing.append("Screen Recording (screenshot capture)")

        print(f"{FLYellow}============================================{CRst}")
        print(f"{FLYellow}Missing required permissions:{CRst}")
        for item in missing:
            print(f"{FLYellow}   - {item}{CRst}")
        print(f"{FLYellow}Grant them to this terminal or Python executable in:{CRst}")
        print(f"{FLCyan}System Settings -> Privacy & Security{CRst}")
        print(f"{FLYellow}Then return here; permission status will be rechecked.{CRst}")
        print(f"{FLYellow}============================================{CRst}")

        subprocess.run(
            ["open", "x-apple.systempreferences:com.apple.preference.security"],
            check=False,
            capture_output=True,
        )

        print(f"{FLCyan}Waiting for permissions... (timeout: {timeout_s}s){CRst}")
        deadline = time.monotonic() + max(0.0, timeout_s)
        while time.monotonic() < deadline:
            accessibility_ok = (
                not accessibility
                or System.check_macos_accessibility_permission()
            )
            screen_recording_ok = (
                not screen_recording
                or System.check_macos_screen_recording_permission()
            )
            if accessibility_ok and screen_recording_ok:
                print(f"{FLGreen}All permissions granted.{CRst}")
                return True
            time.sleep(1.0)

        print(f"{FLRed}Permissions not granted within timeout.{CRst}")
        return False

    @staticmethod
    def wait_for_macos_screen_capture_approval(
        capture_probe: Callable[[], object],
    ) -> bool:
        """Trigger and wait for macOS direct-screen-capture approval.

        On recent macOS versions, the first direct CoreGraphics capture can
        display a second confirmation dialog even when Screen Recording is
        already granted. There is no reliable public preflight result for that
        dialog, so the user explicitly confirms that it has been handled. The
        probe is run again before this method returns successfully.

        The caller supplies a small, non-persistent capture operation so this
        utility does not depend on a particular screenshot library.
        """
        if sys.platform != "darwin":
            return True

        print(f"{FLCyan}Checking direct screen-capture authorization...{CRst}")
        try:
            capture_probe()
        except Exception as exc:
            print(f"{FLRed}Initial screen-capture probe failed: {exc}{CRst}")
            return False

        print()
        print(f"{FLYellow}If macOS displayed a screen-capture dialog, handle it now.{CRst}")
        print(f"{FLYellow}Click Allow, or grant access in System Settings.{CRst}")
        try:
            input(
                f"{FLCyan}After the dialog is closed and access is granted, "
                f"press Enter to continue...{CRst}"
            )
        except (EOFError, OSError):
            print(f"{FLRed}Cannot wait for permission confirmation on this input.{CRst}")
            return False

        if not System.check_macos_screen_recording_permission():
            print(f"{FLRed}Screen Recording permission is still unavailable.{CRst}")
            return False

        try:
            capture_probe()
        except Exception as exc:
            print(f"{FLRed}Screen-capture verification failed: {exc}{CRst}")
            return False

        print(f"{FLGreen}Screen-capture authorization confirmed.{CRst}")
        return True
