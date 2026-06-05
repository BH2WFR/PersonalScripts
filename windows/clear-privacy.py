#!/usr/bin/env python3
"""Clear privacy traces on Windows with explicit section confirmation."""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils import *  # noqa: E402,F403


SectionFunc = Callable[[], None]


def print_help() -> None:
    script_name = os.path.basename(sys.argv[0])
    print(
        f"""
{FLYellow}CLEAR PRIVACY - Windows{CRst}
=======================

Usage:
  python {script_name}
  python {script_name} --force
  python {script_name} --skip-browsers --skip-event-logs

Description:
  Clears Windows Explorer traces, event logs, DNS cache, browser data,
  temp files, credential traces, and other local privacy artifacts.

Options:
  -f, --force          Run enabled sections without confirmation.
  --skip-shell-history Skip Explorer / Shell history section.
  --skip-event-logs    Skip Windows Event Logs section.
  --skip-dns-cache     Skip DNS cache section.
  --skip-additional    Skip additional cleanup section.
  --skip-browsers      Skip browser data cleanup.
  -h, --help           Show this help message.

Notes:
  - Elevation order: sudo -> gsudo -> continue without elevation.
  - Each enabled section asks for confirmation unless --force is used.
  - Browser cleanup is a separate confirmation inside the additional section.

Disclaimer:
  This script clears system and application usage traces. The author
  assumes no responsibility for any system damage, data loss, or
  application malfunction resulting from its use. Use at your own risk.

{FLYellow}Requirements:{CRst}
  Windows only. All tools are built-in (reg, wevtutil, ipconfig, powershell, etc.).
  Optional elevation helpers: {FGray}scoop install sudo gsudo{CRst}
"""
    )


def is_windows() -> bool:
    return sys.platform == "win32"


def is_admin() -> bool:
    if not is_windows():
        return False
    try:
        return bool(getattr(ctypes, "windll").shell32.IsUserAnAdmin())
    except Exception:
        return False


def run(
    cmd: list[str],
    *,
    capture: bool = False,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    if capture:
        if input_text is not None:
            return subprocess.run(cmd, check=False, capture_output=True, text=True, input=input_text)
        return subprocess.run(cmd, check=False, capture_output=True, text=True)

    if input_text is not None:
        return subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            input=input_text,
        )
    return subprocess.run(
        cmd,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def step(text: str) -> None:
    print(f"  {FLCyan}[*]{CRst} {text}")


def ok_msg() -> None:
    print(f"      {FLGreen}OK{CRst}")


def skip_msg(reason: str) -> None:
    print(f"      {FGray}SKIP{CRst} {reason}")


def warn_msg(text: str) -> None:
    print(f"  {FLYellow}[!]{CRst} {text}")


def err_msg(text: str) -> None:
    print(f"  {FLRed}[x]{CRst} {text}")


def prompt_yes_no(prompt: str, *, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    try:
        reply = input(f"{prompt} ({suffix}) ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not reply:
        return default
    return reply in {"y", "yes"}


def confirm_section(args: argparse.Namespace, title: str) -> bool:
    if args.force:
        return True
    return prompt_yes_no(f"{FLYellow}Run {title}?{CRst}")


def try_relaunch_with_helper(helper: str) -> bool:
    helper_path = shutil.which(helper)
    if helper_path is None:
        return False

    cmd = [helper_path, sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:]]
    try:
        result = subprocess.run(cmd)
    except Exception as exc:
        warn_msg(f"{FGray}{helper}{CRst} elevation failed: {FLRed}{exc}{CRst}")
        return False

    if result.returncode == 0:
        raise SystemExit(0)

    warn_msg(
        f"{FGray}{helper}{CRst} exited with code {FLRed}{result.returncode}{CRst}; "
        "continuing without elevation."
    )
    return False


def env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def remove_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def remove_tree(path: Path) -> None:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def clear_dir(path: Path) -> None:
    if not path.is_dir():
        return
    for item in path.iterdir():
        remove_tree(item)


def reg_key_exists(path: str) -> bool:
    return run(["reg", "query", path]).returncode == 0


def delete_reg_key(path: str) -> None:
    if reg_key_exists(path):
        run(["reg", "delete", path, "/f"])


def delete_reg_value(path: str, name: str) -> None:
    if reg_key_exists(path):
        run(["reg", "delete", path, "/v", name, "/f"])


def empty_recycle_bin() -> None:
    try:
        getattr(ctypes, "windll").shell32.SHEmptyRecycleBinW(None, None, 0x00000001 | 0x00000002 | 0x00000004)
    except Exception:
        pass


def clear_shell_history() -> None:
    empty_recycle_bin()

    shell_bag_paths = [
        r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\Bags",
        r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\BagMRU",
        r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\ShellNoRoam\Bags",
        r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\ShellNoRoam\BagMRU",
        r"HKCU\Software\Classes\Wow6432Node\Local Settings\Software\Microsoft\Windows\Shell\Bags",
        r"HKCU\Software\Classes\Wow6432Node\Local Settings\Software\Microsoft\Windows\Shell\BagMRU",
        r"HKCU\Software\Microsoft\Windows\Shell\Bags",
        r"HKCU\Software\Microsoft\Windows\Shell\BagMRU",
        r"HKCU\Software\Microsoft\Windows\ShellNoRoam\BagMRU",
        r"HKCU\Software\Microsoft\Windows\ShellNoRoam\Bags",
    ]
    mui_cache_paths = [
        r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache",
        r"HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\ShellNoRoam\MuiCache",
        r"HKCU\Software\Classes\Wow6432Node\Local Settings\Software\Microsoft\Windows\Shell\MuiCache",
    ]
    explorer_paths = [
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist",
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\RunMRU",
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\TypedPaths",
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\WordWheelQuery",
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FeatureUsage",
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\LastVisitedPidlMRU",
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\OpenSavePidlMRU",
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\SearchHistory",
    ]

    for reg_path in shell_bag_paths + mui_cache_paths + explorer_paths:
        delete_reg_key(reg_path)

    delete_reg_key(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Search\RecentApps")
    delete_reg_key(r"HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Compatibility Assistant\Store")
    delete_reg_key(r"HKCU\Software\Microsoft\Terminal Server Client\Default")
    delete_reg_key(r"HKCU\Software\Microsoft\Terminal Server Client\Servers")

    appdata = env_path("APPDATA")
    localappdata = env_path("LOCALAPPDATA")
    windir = env_path("WINDIR")
    if appdata:
        clear_dir(appdata / "Microsoft/Windows/Recent")
        clear_dir(appdata / "Microsoft/Windows/Recent/AutomaticDestinations")
        clear_dir(appdata / "Microsoft/Windows/Recent/CustomDestinations")
    if windir:
        clear_dir(windir / "Prefetch")
        clear_dir(windir / "appcompat/Programs")
    if localappdata:
        delete_reg_value(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\TypedPaths", "url1")


def clear_event_logs() -> None:
    result = run(["wevtutil", "el"], capture=True)
    if result.returncode == 0 and result.stdout:
        for raw_name in result.stdout.splitlines():
            log_name = raw_name.strip()
            if log_name:
                run(["wevtutil", "cl", log_name])


def clear_dns_cache() -> None:
    run(["ipconfig", "/flushdns"])
    run(["powershell", "-NoProfile", "-Command", "Clear-DnsClientCache"], capture=False)


def iter_cmdkey_targets() -> list[str]:
    result = run(["cmdkey", "/list"], capture=True)
    if result.returncode != 0 or not result.stdout:
        return []
    targets: list[str] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("target:"):
            target = stripped.split(":", 1)[1].strip()
            if target:
                targets.append(target)
    return targets


def clear_credential_manager() -> None:
    for target in iter_cmdkey_targets():
        run(["cmdkey", f"/delete:{target}"])


def clear_powershell_history() -> None:
    appdata = env_path("APPDATA")
    if not appdata:
        return
    for path in [
        appdata / "Microsoft/Windows/PowerShell/PSReadLine/ConsoleHost_history.txt",
        appdata / "Microsoft/Windows/PowerShell/PSReadLine/Visual Studio Code Host_history.txt",
    ]:
        remove_file(path)


def clear_clipboard() -> None:
    run(["cmd", "/c", "echo off | clip"])


def clear_browser_data() -> None:
    localappdata = env_path("LOCALAPPDATA")
    if not localappdata:
        return

    browser_bases = [
        localappdata / "Microsoft/Edge/User Data",
        localappdata / "Google/Chrome/User Data",
    ]
    db_files = [
        "History",
        "History-journal",
        "Cookies",
        "Cookies-journal",
        "Top Sites",
        "Top Sites-journal",
        "Favicons",
        "Favicons-journal",
        "Login Data",
        "Login Data-journal",
        "Web Data",
        "Web Data-journal",
        "Shortcuts",
        "Shortcuts-journal",
        "Network Action Predictor",
        "Network Action Predictor-journal",
        "Media History",
        "Media History-journal",
    ]
    cache_dirs = [
        "Cache",
        "Code Cache",
        "GPUCache",
        "Service Worker",
        "IndexedDB",
        "Local Storage",
        "Session Storage",
        "WebStorage",
    ]

    for base in browser_bases:
        if not base.is_dir():
            continue
        for profile_dir in base.iterdir():
            if not profile_dir.is_dir():
                continue
            for file_name in db_files:
                remove_file(profile_dir / file_name)
            for dir_name in cache_dirs:
                clear_dir(profile_dir / dir_name)


def clear_thumbnail_and_icon_cache() -> None:
    localappdata = env_path("LOCALAPPDATA")
    if not localappdata:
        return
    explorer_dir = localappdata / "Microsoft/Windows/Explorer"
    clear_dir(explorer_dir)
    remove_file(localappdata / "IconCache.db")
    for pattern in ("thumbcache_*.db", "iconcache_*.db"):
        for file_path in explorer_dir.glob(pattern):
            remove_file(file_path)


def clear_temp_and_cache_dirs() -> None:
    temp = env_path("TEMP")
    windir = env_path("WINDIR")
    localappdata = env_path("LOCALAPPDATA")
    allusers = env_path("ALLUSERSPROFILE")

    if temp:
        clear_dir(temp)
    if windir:
        clear_dir(windir / "Temp")
        clear_dir(windir / "SoftwareDistribution/DeliveryOptimization")
        clear_dir(windir / "CCM/Cache")
        clear_dir(windir / "CCMCache")
    if localappdata:
        clear_dir(localappdata / "Microsoft/Windows/INetCache")
        clear_dir(localappdata / "Microsoft/Windows/INetCookies")
        clear_dir(localappdata / "Microsoft/Internet Explorer/Recovery")
        clear_dir(localappdata / "Packages/Microsoft.WindowsStore_8wekyb3d8bbwe/LocalCache")
        clear_dir(localappdata / "Packages/Microsoft.Windows.Search_cw5n1h2txyewy/LocalState/AppIconCache")
        clear_dir(localappdata / "Microsoft/Windows/Notifications")
        clear_dir(localappdata / "Microsoft/Windows/Fonts")
        clear_dir(localappdata / "Microsoft/Windows/WER")
    if allusers:
        clear_dir(Path(allusers) / "Microsoft/Windows/WER/ReportArchive")
        clear_dir(Path(allusers) / "Microsoft/Windows/WER/ReportQueue")


def clear_network_traces() -> None:
    run(["arp", "-d", "*"])
    run(["nbtstat", "-R"])
    run(["net", "use", "*", "/delete", "/y"])
    run(["netsh", "branchcache", "reset"])


def clear_ie_and_search_traces() -> None:
    delete_reg_key(r"HKCU\Software\Microsoft\Internet Explorer\TypedURLs")
    delete_reg_key(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Search")
    delete_reg_key(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Notifications\Settings")


def clear_print_spooler() -> None:
    windir = env_path("WINDIR")
    if not windir:
        return
    run(["net", "stop", "spooler"])
    clear_dir(windir / "System32/spool/PRINTERS")
    run(["net", "start", "spooler"])


def clear_additional(args: argparse.Namespace) -> None:
    clear_network_traces()
    clear_powershell_history()
    clear_clipboard()
    clear_thumbnail_and_icon_cache()
    clear_temp_and_cache_dirs()
    clear_ie_and_search_traces()

    warn_msg(
        "System credential cleanup target: "
        f"{FGray}Credential Manager / cmdkey{CRst}. This may sign you out of saved network,"
        " RDP, and application logins."
    )
    if args.force or prompt_yes_no(f"{FLYellow}Also clear stored Credential Manager entries?{CRst}"):
        clear_credential_manager()
    else:
        skip_msg("Credential Manager")

    if not args.skip_browsers:
        warn_msg(
            "Browser cleanup target: "
            f"{FGray}Microsoft Edge{CRst} and {FGray}Google Chrome{CRst}, including history,"
            " cookies, cached data, and saved session artifacts."
        )
        if args.force or prompt_yes_no(f"{FLYellow}Also clear Edge and Chrome profile data?{CRst}"):
            clear_browser_data()
        else:
            skip_msg("browser data")

    if args.force or prompt_yes_no(f"{FLYellow}Also clear print spooler jobs?{CRst}"):
        clear_print_spooler()
    else:
        skip_msg("print spooler jobs")


def print_banner(args: argparse.Namespace) -> None:
    print(f"{FLYellow}{'=' * 60}{CRst}")
    print(f"{FLYellow}  PRIVACY CLEANUP - Windows{CRst}")
    print(f"{FLYellow}  Explicit per-section confirmation enabled.{CRst}")
    print(f"{FLYellow}{'=' * 60}{CRst}")
    print()
    print("  Enabled sections:")
    if not args.skip_shell_history:
        print("    1. Explorer / Shell history")
    if not args.skip_event_logs:
        print("    2. Windows Event Logs")
    if not args.skip_dns_cache:
        print("    3. DNS cache")
    if not args.skip_additional:
        print("    4. Additional cleanup")
    print()


def main() -> None:
    Utils.set_locale_utf8()

    if not is_windows():
        err_msg(f"This script only runs on Windows. Current platform: {FGray}{sys.platform}{CRst}")
        raise SystemExit(1)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-f", "--force", action="store_true")
    parser.add_argument("--skip-shell-history", action="store_true")
    parser.add_argument("--skip-event-logs", action="store_true")
    parser.add_argument("--skip-dns-cache", action="store_true")
    parser.add_argument("--skip-additional", action="store_true")
    parser.add_argument("--skip-browsers", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args()

    if args.help:
        print_help()
        return

    print_banner(args)
    if not is_admin():
        warn_msg(
            "Administrator privileges not detected. Trying "
            f"{FGray}sudo{CRst}, then {FGray}gsudo{CRst}."
        )
        elevated = try_relaunch_with_helper("sudo") or try_relaunch_with_helper("gsudo")
        if not elevated:
            warn_msg("Elevation unavailable. Admin-only cleanup may be skipped or only partially work.")

    start_time = time.time()

    if not args.skip_shell_history and confirm_section(args, "Section 1: Explorer / Shell history"):
        step("Section 1: Explorer / Shell history")
        clear_shell_history()
        ok_msg()

    if not args.skip_event_logs and confirm_section(args, "Section 2: Windows Event Logs"):
        step("Section 2: Windows Event Logs")
        clear_event_logs()
        ok_msg()

    if not args.skip_dns_cache and confirm_section(args, "Section 3: DNS cache"):
        step("Section 3: DNS cache")
        clear_dns_cache()
        ok_msg()

    if not args.skip_additional and confirm_section(args, "Section 4: additional cleanup"):
        step("Section 4: Additional cleanup")
        clear_additional(args)
        ok_msg()

    elapsed = time.time() - start_time
    print()
    print(f"{FLGreen}Done.{CRst} Elapsed: {elapsed:.1f}s")
    print(
        f"{FLYellow}Warning:{CRst} Restarting {FGray}Explorer{CRst} or rebooting is recommended"
        " for full effect."
    )


if __name__ == "__main__":
    raise sys.exit(main())
