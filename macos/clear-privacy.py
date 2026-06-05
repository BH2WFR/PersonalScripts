#!/usr/bin/env python3
"""Clear privacy traces on macOS with explicit per-section confirmation."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils import *  # noqa: E402,F403


HOME = Path.home()
LIB = HOME / "Library"


def print_help() -> None:
    script_name = os.path.basename(sys.argv[0])
    print(
        f"""
{FLYellow}CLEAR PRIVACY - macOS{CRst}
=====================

Usage:
  python3 {script_name}
  python3 {script_name} --force
  sudo python3 {script_name} --skip-system

Description:
  Clears recent items, Finder and shell traces, browser data, caches,
  temp files, and selected system traces from a macOS machine.

Options:
  -f, --force          Run enabled sections without confirmation.
  --skip-recent        Skip recent items / Finder / shell section.
  --skip-caches        Skip caches and temp files section.
  --skip-browsers      Skip browser data section.
  --skip-system        Skip system traces section.
  --skip-apps          Skip application MRU and developer traces section.
  -h, --help           Show this help message.

Notes:
  - Root is only needed for some system-level cleanup.
  - Elevation order: sudo -> continue without elevation.
  - Each enabled section asks for confirmation unless --force is used.

Disclaimer:
  This script clears system and application usage traces. The author
  assumes no responsibility for any system damage, data loss, or
  application malfunction resulting from its use. Use at your own risk.

{FLYellow}Requirements:{CRst}
  macOS only. All tools are built-in (defaults, killall, qlmanage, dscacheutil, etc.).
  Optional: {FGray}brew install trash{CRst} (for Trash emptying)
"""
    )


def is_root() -> bool:
    return sys.platform == "darwin" and os.geteuid() == 0


def run(
    cmd: list[str],
    *,
    capture: bool = False,
    input_data: bytes | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess:
    if capture:
        if input_data is not None:
            return subprocess.run(
                cmd,
                check=check,
                capture_output=True,
                text=True,
                input=input_data.decode("utf-8", errors="ignore"),
            )
        return subprocess.run(cmd, check=check, capture_output=True, text=True)

    if input_data is not None:
        return subprocess.run(
            cmd,
            check=check,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            input=input_data,
        )
    return subprocess.run(cmd, check=check, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def rm_f(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except (PermissionError, OSError):
        pass


def rm_rf(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink(missing_ok=True)
    except (PermissionError, OSError):
        pass


def clear_dir(path: Path) -> None:
    if not path.is_dir():
        return
    for item in path.iterdir():
        rm_rf(item)


def delete_plist_keys(domain: str, keys: list[str]) -> None:
    for key in keys:
        run(["defaults", "delete", domain, key])


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


def try_relaunch_with_sudo() -> bool:
    sudo_path = shutil.which("sudo")
    if sudo_path is None:
        return False

    cmd = [sudo_path, sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:]]
    try:
        result = subprocess.run(cmd)
    except Exception as exc:
        warn_msg(f"{FGray}sudo{CRst} elevation failed: {FLRed}{exc}{CRst}")
        return False

    if result.returncode == 0:
        raise SystemExit(0)

    warn_msg(
        f"{FGray}sudo{CRst} exited with code {FLRed}{result.returncode}{CRst}; "
        "continuing without elevation."
    )
    return False


def clear_recent_items() -> None:
    sfl_dir = LIB / "Application Support/com.apple.sharedfilelist"
    if sfl_dir.is_dir():
        for pattern in ("*.sfl", "*.sfl2", "*.sfl3"):
            for file_path in sfl_dir.glob(pattern):
                rm_f(file_path)

    rm_f(LIB / "Preferences/com.apple.recentitems.plist")
    run(["defaults", "delete", "com.apple.finder", "FXRecentFolders"])


def clear_finder_state() -> None:
    delete_plist_keys(
        "com.apple.finder",
        [
            "FXDesktopVolumePositions",
            "FXRecentFolders",
            "FXConnectToLastURL",
            "NSNavLastRootDirectory",
            "NSNavRecentPlaces",
            "NSNavPanelExpandedSizeForOpenMode",
            "NSNavPanelExpandedSizeForSaveMode",
            "NSToolbar Configuration Browser",
        ],
    )
    clear_dir(LIB / "Saved Application State/com.apple.finder.savedState")
    rm_f(LIB / "Preferences/com.apple.sidebarlists.plist")
    delete_plist_keys("com.apple.finder", ["SidebarDevices", "SidebarPlaces"])


def clear_ds_store_traces() -> None:
    targets = [
        HOME / "Desktop",
        HOME / "Documents",
        HOME / "Downloads",
        HOME / "Movies",
        HOME / "Music",
        HOME / "Pictures",
        HOME / "Public",
    ]
    for base in targets:
        if not base.exists():
            continue
        for ds_store in base.rglob(".DS_Store"):
            rm_f(ds_store)


def clear_shell_history() -> None:
    rm_f(HOME / ".bash_history")
    rm_f(HOME / ".zsh_history")
    rm_f(HOME / ".zhistory")
    rm_f(HOME / ".sh_history")
    clear_dir(HOME / ".zsh_sessions")
    rm_f(HOME / ".local/share/fish/fish_history")


def clear_terminal_saved_state() -> None:
    clear_dir(LIB / "Saved Application State/com.apple.Terminal.savedState")
    clear_dir(LIB / "Saved Application State/com.googlecode.iterm2.savedState")
    clear_dir(LIB / "Application Support/iTerm2/SavedState")


def clear_dock_recent_apps() -> None:
    delete_plist_keys("com.apple.dock", ["recent-apps"])
    run(["killall", "Dock"])


def clear_notification_center() -> None:
    clear_dir(LIB / "Application Support/NotificationCenter")
    rm_f(LIB / "Preferences/com.apple.notificationcenterui.plist")


def clear_quicklook_cache() -> None:
    clear_dir(LIB / "Caches/com.apple.QuickLookDaemon")
    run(["qlmanage", "-r", "cache"])


def clear_icon_cache() -> None:
    rm_f(LIB / "Caches/com.apple.iconservices.store")
    clear_dir(LIB / "Caches/com.apple.iconservices")


def clear_caches() -> None:
    clear_dir(LIB / "Caches")
    if is_root():
        clear_dir(Path("/Library/Caches"))


def clear_temp_files() -> None:
    clear_dir(LIB / "Caches/TemporaryItems")
    if is_root():
        clear_dir(Path("/tmp"))
        clear_dir(Path("/var/tmp"))


def clear_font_cache() -> None:
    clear_dir(LIB / "Caches/com.apple.ATS")
    if is_root():
        clear_dir(Path("/Library/Caches/com.apple.ATS"))
        run(["atsutil", "databases", "-remove"])
    run(["atsutil", "server", "-shutdown"])
    run(["atsutil", "server", "-ping"])


def clear_homebrew_cache() -> None:
    for brew_cache in [
        Path("/usr/local/Library/Caches/Homebrew"),
        Path("/opt/homebrew/Library/Caches/Homebrew"),
    ]:
        clear_dir(brew_cache)
    run(["brew", "cleanup", "--prune=all", "-s"])


def clear_safari() -> None:
    safari = LIB / "Safari"
    for file_name in [
        "History.db",
        "History.db-shm",
        "History.db-wal",
        "HistoryIndex.sk",
        "LastSession.plist",
        "RecentlyClosedTabs.plist",
        "TopSites.plist",
        "Cookies.binarycookies",
    ]:
        rm_f(safari / file_name)

    clear_dir(LIB / "Caches/com.apple.Safari")
    clear_dir(LIB / "Caches/com.apple.Safari.SafeBrowsing")
    clear_dir(LIB / "Caches/com.apple.WebKit")
    clear_dir(LIB / "WebKit/WebsiteData/LocalStorage")
    clear_dir(LIB / "WebKit/WebsiteData/IndexedDB")
    clear_dir(LIB / "WebKit/WebsiteData/ServiceWorkers")
    clear_dir(safari / "Favicon Cache")
    clear_dir(safari / "Touch Icons Cache")
    rm_f(LIB / "Preferences/com.apple.Safari.SandboxBroker.plist")
    delete_plist_keys("com.apple.Safari", ["DownloadsLastPath", "DownloadsPath"])

    safari_tp = LIB / "Safari Technology Preview"
    if safari_tp.is_dir():
        rm_f(safari_tp / "History.db")
        rm_f(safari_tp / "Cookies.binarycookies")


def clear_chromium_browsers() -> None:
    bases = [
        LIB / "Application Support/Google/Chrome",
        LIB / "Application Support/Microsoft Edge",
        LIB / "Application Support/BraveSoftware/Brave-Browser",
        LIB / "Application Support/Chromium",
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
    ]

    for base in bases:
        if not base.is_dir():
            continue
        for profile_dir in base.iterdir():
            if not profile_dir.is_dir():
                continue
            for file_name in db_files:
                rm_f(profile_dir / file_name)
            for dir_name in cache_dirs:
                clear_dir(profile_dir / dir_name)


def clear_dns_cache() -> None:
    if not is_root():
        return
    run(["dscacheutil", "-flushcache"])
    run(["killall", "-HUP", "mDNSResponder"])
    run(["killall", "-HUP", "mDNSResponderHelper"])


def clear_event_logs() -> None:
    if not is_root():
        return
    run(["log", "erase", "--all"])
    clear_dir(Path("/var/log/asl"))
    clear_dir(Path("/Library/Logs/DiagnosticReports"))
    clear_dir(LIB / "Logs/DiagnosticReports")


def clear_system_logs() -> None:
    if not is_root():
        return
    for log_dir in [Path("/var/log"), Path("/private/var/log")]:
        if not log_dir.is_dir():
            continue
        for file_path in log_dir.iterdir():
            if file_path.is_file() and file_path.suffix in {".log", ".out"}:
                try:
                    run(["truncate", "-s", "0", str(file_path)])
                except Exception:
                    pass


def clear_spotlight_history() -> None:
    delete_plist_keys("com.apple.spotlight", ["findItemsLastUsedDateDict"])
    clear_dir(LIB / "Caches/com.apple.helpd")
    if is_root():
        run(["mdutil", "-E", "/"])
    run(["mdutil", "-E", str(HOME)])


def clear_arp_cache() -> None:
    if is_root():
        run(["arp", "-ad"])


def clear_launch_services_db() -> None:
    run(
        [
            "/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/"
            "LaunchServices.framework/Versions/A/Support/lsregister",
            "-kill",
            "-r",
            "-domain",
            "local",
            "-domain",
            "user",
        ]
    )


def clear_clipboard() -> None:
    run(["pbcopy"], input_data=b"")


def clear_app_mru() -> None:
    delete_plist_keys("com.apple.QuickTimePlayerX", ["MGRecentURLS", "MGRecentURLsDocumentEntered"])
    delete_plist_keys("com.apple.Preview", ["PVRecentDocuments", "NSNavRecentPlaces"])
    delete_plist_keys("com.apple.TextEdit", ["NSNavRecentPlaces", "LastOpenDirectory"])
    delete_plist_keys("com.apple.DiskUtility", ["DUSharedDefaultsRecentlyRestored"])
    delete_plist_keys("com.apple.Console", ["NSNavRecentPlaces"])


def clear_xcode_derived_data() -> None:
    clear_dir(LIB / "Developer/Xcode/DerivedData")
    clear_dir(LIB / "Developer/Xcode/Archives")
    clear_dir(LIB / "Developer/Xcode/iOS DeviceSupport")
    clear_dir(LIB / "Developer/CoreSimulator/Devices")


def clear_python_pycache() -> None:
    targets = [
        HOME / "Desktop",
        HOME / "Documents",
        HOME / "Downloads",
        HOME / "Projects",
        HOME / "Developer",
    ]
    for base in targets:
        if not base.exists():
            continue
        for cache_dir in base.rglob("__pycache__"):
            rm_rf(cache_dir)
        for pyc in base.rglob("*.pyc"):
            rm_f(pyc)


def print_banner(args: argparse.Namespace) -> None:
    print(f"{FLYellow}{'=' * 58}{CRst}")
    print(f"{FLYellow}  PRIVACY CLEANUP - macOS{CRst}")
    print(f"{FLYellow}  Explicit per-section confirmation enabled.{CRst}")
    print(f"{FLYellow}{'=' * 58}{CRst}")
    print()
    print("  Enabled sections:")
    if not args.skip_recent:
        print("    1. Recent items / Finder state / shell history")
    if not args.skip_caches:
        print("    2. Caches / temp files / local caches")
    if not args.skip_browsers:
        print("    3. Browser data")
    if not args.skip_system:
        print("    4. System traces")
    if not args.skip_apps:
        print("    5. Application MRU / developer traces")
    print()
    if not is_root() and not args.skip_system:
        print(f"  {FGray}System cleanup will partially skip root-only steps unless elevation succeeds.{CRst}")
        print()


def main() -> None:
    if sys.platform != "darwin":
        err_msg(f"This script only runs on macOS. Current platform: {FGray}{sys.platform}{CRst}")
        raise SystemExit(1)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-f", "--force", action="store_true")
    parser.add_argument("--skip-recent", action="store_true")
    parser.add_argument("--skip-caches", action="store_true")
    parser.add_argument("--skip-browsers", action="store_true")
    parser.add_argument("--skip-system", action="store_true")
    parser.add_argument("--skip-apps", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args()

    if args.help:
        print_help()
        return

    print_banner(args)
    if not is_root():
        warn_msg(f"Root privileges not detected. Trying {FGray}sudo{CRst}.")
        elevated = try_relaunch_with_sudo()
        if not elevated:
            warn_msg("Elevation unavailable. Root-only cleanup will be skipped.")

    start_time = time.time()

    if not args.skip_recent and confirm_section(args, "Section 1: recent items / Finder / shell history"):
        step("Section 1: Recent items / Finder state / shell history")
        clear_recent_items()
        clear_finder_state()
        clear_shell_history()
        clear_terminal_saved_state()
        clear_notification_center()
        clear_dock_recent_apps()
        clear_ds_store_traces()
        ok_msg()

    if not args.skip_caches and confirm_section(args, "Section 2: caches / temp files"):
        step("Section 2: Caches / temp files")
        clear_caches()
        clear_temp_files()
        clear_quicklook_cache()
        clear_icon_cache()
        clear_font_cache()
        if args.force or prompt_yes_no(f"{FLYellow}Also clear Homebrew download cache?{CRst}"):
            clear_homebrew_cache()
        else:
            skip_msg("Homebrew cache")
        ok_msg()

    if not args.skip_browsers and confirm_section(args, "Section 3: browser data"):
        step("Section 3: Browser data")
        warn_msg(
            "Browser cleanup target: "
            f"{FGray}Safari{CRst}, {FGray}Chrome{CRst}, {FGray}Edge{CRst}, "
            f"{FGray}Brave{CRst}, and {FGray}Chromium{CRst}, including history,"
            " cookies, caches, and session-related artifacts."
        )
        clear_safari()
        clear_chromium_browsers()
        ok_msg()

    if not args.skip_system and confirm_section(args, "Section 4: system traces"):
        step("Section 4: System traces")
        if is_root():
            clear_dns_cache()
            clear_event_logs()
            clear_system_logs()
            clear_arp_cache()
        else:
            skip_msg("root-only DNS/log/ARP steps")
        clear_spotlight_history()
        if args.force or prompt_yes_no(f"{FLYellow}Reset LaunchServices database as well?{CRst}"):
            clear_launch_services_db()
        else:
            skip_msg("LaunchServices reset")
        ok_msg()

    if not args.skip_apps and confirm_section(args, "Section 5: application MRU / developer traces"):
        step("Section 5: Application MRU / developer traces")
        clear_app_mru()
        clear_clipboard()
        if args.force or prompt_yes_no(f"{FLYellow}Also clear Xcode derived data and simulator caches?{CRst}"):
            clear_xcode_derived_data()
        else:
            skip_msg("Xcode derived data")
        if args.force or prompt_yes_no(f"{FLYellow}Also clear Python __pycache__ and .pyc files in common work folders?{CRst}"):
            clear_python_pycache()
        else:
            skip_msg("Python cache files")
        ok_msg()

    elapsed = time.time() - start_time
    print()
    print(f"{FLGreen}Done.{CRst} Elapsed: {elapsed:.1f}s")
    print(
        f"{FLYellow}Warning:{CRst} Restart Finder/Dock if needed with "
        f"{FGray}killall Finder Dock{CRst}"
    )


if __name__ == "__main__":
    raise sys.exit(main())
