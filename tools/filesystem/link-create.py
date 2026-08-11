#!/usr/bin/env python3
# 软链接/硬链接 创建工具
# Linux/macos 中，使用 ln 命令创建软链接（符号链接）或硬链接。
# Windows 中，使用 mklink 命令创建符号链接或硬链接；如目标为文件夹，则支持 symlinkd 和 junction
# 如果输入的路径中只有一个目录，则会提供额外选项：链接目录本身，还是链接目录内的内容（展平或递归镜像）

import os
import sys
from typing import Optional

import enum

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402


def main() -> int:
    Console.print_banner("LINK CREATION TOOL")

    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
    {FLYellow}LINK CREATION TOOL{CRst}
    ==================

    Usage:
      python {script_name} <path1> <path2> ...   specify paths, skip interaction
      python {script_name}                        no arguments, interactive mode
      python {script_name} --help                 show this help

    {FLYellow}Supported Link Types:{CRst}
      Windows:
        Files   - Symlink (absolute or ..\\ relative path) / Hardlink (absolute path)
        Dirs    - SymlinkD (absolute, ..\\ relative, or \\ root-relative path) / Junction (absolute path)
      Linux/macOS:
        Files   - Symlink (absolute or ../ relative path) / Hardlink (absolute path)
        Dirs    - Symlink (absolute or ../ relative path)

    {FLYellow}Single Directory Mode{CRst} (when only one directory is provided):
      0  Link the directory itself
      1  Flat-link contents inside the directory (files/subdirs, same level)
      2  Recursively mirror directory structure (real dirs, linked files)

    {FLYellow}Interactive Workflow:{CRst}
      1. Enter source paths (multi-line, Ctrl+Z/Ctrl+D to end)
      2. Choose link type (separately for files and directories)
      3. Enter target directory
      4. Choose how target paths are stored in symlinks
      5. Confirm and execute; conflicts can be skip/skip all/overwrite/overwrite all

    {FLYellow}Requirements:{CRst}
      No external dependencies. Uses built-in os.symlink/os.link; Windows uses mklink (cmd built-in).
    """)
        return 0



    IS_WIN = os.name == "nt"


    #============ 用户交互 - 读取路径列表 ===========
    paths: list[str] = []
    if len(sys.argv) > 1:
        for i in range(1, len(sys.argv)):
            p = sys.argv[i].strip()
            if p:
                paths.append(p)
    else:
        paths = Input.resolve_input_paths_multi(
            prompt_text="Enter source paths (one per line, supports wildcards like *.txt)",
            path_type="any",
            glob=True,
        )

    #============ 分类路径 ===========
    class PathCategory(enum.Enum):
        FILE = 1
        DIRECTORY = 2
        OTHER = 3  # symlink, socket, etc.

    files: list[str] = []
    dirs: list[str] = []
    others: list[str] = []

    for p in paths:
        if os.path.islink(p):
            others.append(p)
        elif os.path.isfile(p):
            files.append(p)
        elif os.path.isdir(p):
            dirs.append(p)
        else:
            others.append(p)

    print(f"  {FLYellow}Files{CRst}  : {FLGreen}{len(files)}{CRst}")
    print(f"  {FLYellow}Dirs{CRst}   : {FLGreen}{len(dirs)}{CRst}")
    print(f"  {FLBlue  }Others{CRst} : {FGray}{len(others)}{CRst}")

    if others:
        print(f"{FLYellow}[WARNING] Unknown/special file types detected (symlinks, sockets, etc.) — these will be skipped.{CRst}")

    total = len(files) + len(dirs)
    if total == 0:
        print(f"{FLRed}No valid paths to process (only unlinkable special files found). EXIT...{CRst}\n")
        return 1


    #============ 选择链接类型 ===========
    class LinkType(enum.Enum):
        SYMLINK = 1       # 软链接（文件/文件夹通用，Linux; Windows 文件）
        SYMLINKD = 2      # Windows 目录软链接
        JUNCTION = 3      # Windows 目录 junction
        HARDLINK = 4      # 硬链接

    class TargetPathMode(enum.Enum):
        ABSOLUTE = 1            # C:\path\to\target or /path/to/target
        RELATIVE = 2            # ..\target on Windows, ../target on POSIX
        WIN_DRIVE_ROOT = 3      # \path\to\target, Windows SymlinkD only

    file_link_type: Optional[LinkType] = None
    dir_link_type: Optional[LinkType] = None

    def ask_file_link_type():
        """询问文件链接类型，返回 LinkType"""
        return Menu.select(
            [
                MenuOption(["1"], f"Symlink (soft link{', supports relative paths' if IS_WIN else ''})", value=LinkType.SYMLINK),
                MenuOption(["2"], "Hardlink (hard link, always uses absolute source path)", value=LinkType.HARDLINK),
            ],
            prompt="Choose for files", default_key="1",
        )

    def ask_dir_link_type():
        """询问目录链接类型，返回 LinkType"""
        if IS_WIN:
            return Menu.select(
                [
                    MenuOption(["1"], "SymlinkD (directory soft link, supports relative paths)", value=LinkType.SYMLINKD),
                    MenuOption(["2"], "Junction (directory junction, does NOT support relative paths)", value=LinkType.JUNCTION),
                ],
                prompt="Choose for directories", default_key="1",
            )
        else:
            return LinkType.SYMLINK


    #============ 单文件夹特殊处理 ===========
    mirror_mode: Optional[int] = 0      # 0=直接链接, 1=展平内容, 2=递归镜像
    mirror_source_dir: str = ""    # 仅 mirror_mode 1/2 使用，保存原始目录路径
    is_single_dir = len(dirs) == 1 and len(files) == 0

    if is_single_dir:
        print(f"\n{FLYellow}Only one directory detected. Additional options:{CRst}")
        mirror_mode = Menu.select(
            [
                MenuOption(["0"], "Link the directory itself", value=0),
                MenuOption(["1"], "Link files/subdirs inside the directory (flat, same level)", value=1),
                MenuOption(["2"], "Recursively mirror directory structure with links", value=2),
            ],
            prompt="Choose", default_key="0", separator=False,
        )

    if mirror_mode == 0:
        # 直接链接模式：根据现有分类询问链接类型
        if files:
            print(f"\n{FLYellow}--- File link type ---{CRst}")
            file_link_type = ask_file_link_type()
        if dirs:
            print(f"\n{FLYellow}--- Directory link type ---{CRst}")
            dir_link_type = ask_dir_link_type()

    elif mirror_mode == 1:
        # 展平模式：扫描一级内容，分别询问文件和文件夹链接类型
        mirror_source_dir = os.path.abspath(dirs[0])
        print(f"\n{FLYellow}  -> scanning contents of: {mirror_source_dir}{CRst}")
        _files: list[str] = []
        _dirs: list[str] = []
        for entry in os.listdir(mirror_source_dir):
            entry_path = os.path.join(mirror_source_dir, entry)
            if os.path.islink(entry_path):
                print(f"  {FGray}SKIP (special): {entry}{CRst}")
            elif os.path.isfile(entry_path):
                _files.append(entry_path)
            elif os.path.isdir(entry_path):
                _dirs.append(entry_path)
            else:
                print(f"  {FGray}SKIP (special): {entry}{CRst}")

        print(f"  {FLYellow}Files{CRst}  : {FLGreen}{len(_files)}{CRst}")
        print(f"  {FLYellow}Dirs{CRst}   : {FLGreen}{len(_dirs)}{CRst}")

        if not _files and not _dirs:
            print(f"{FLRed}No linkable contents found. EXIT...{CRst}\n")
            return 1

        files.clear(); dirs.clear()
        files.extend(_files); dirs.extend(_dirs)

        if _files:
            print(f"\n{FLYellow}--- File link type ---{CRst}")
            file_link_type = ask_file_link_type()
        if _dirs:
            print(f"\n{FLYellow}--- Directory link type ---{CRst}")
            dir_link_type = ask_dir_link_type()

    elif mirror_mode == 2:
        # 递归镜像模式：仅询问文件链接类型，目录默认使用 symlink/symlinkd
        mirror_source_dir = os.path.abspath(dirs[0])
        print(f"\n{FLYellow}  -> scanning contents of: {mirror_source_dir}{CRst}")
        _files: list[str] = []
        _dirs: list[str] = []
        for dirpath, dirnames, filenames in os.walk(mirror_source_dir):
            for name in filenames:
                fp = os.path.join(dirpath, name)
                if not os.path.islink(fp) and os.path.isfile(fp):
                    _files.append(fp)
            for name in dirnames:
                dp = os.path.join(dirpath, name)
                if not os.path.islink(dp) and os.path.isdir(dp):
                    _dirs.append(dp)

        print(f"  {FLYellow}Files{CRst}  : {FLGreen}{len(_files)}{CRst}")
        print(f"  {FLYellow}Dirs{CRst}   : {FLGreen}{len(_dirs)}{CRst}")

        if not _files and not _dirs:
            print(f"{FLRed}No linkable contents found. EXIT...{CRst}\n")
            return 1

        files.clear(); dirs.clear()
        files.extend(_files); dirs.extend(_dirs)

        if _files:
            print(f"\n{FLYellow}--- File link type ---{CRst}")
            file_link_type = ask_file_link_type()
        # 目录默认使用 symlink（Linux）或 symlinkd（Windows）
        if _dirs:
            dir_link_type = LinkType.SYMLINKD if IS_WIN else LinkType.SYMLINK


    #============ 目标路径 ===========
    print(f"\n{FLYellow}--- Target directory ---{CRst}")
    target_dir = input(f"{FLCyan}Enter target directory: {CRst}").strip()
    if not target_dir:
        print(f"{FLRed}No target directory provided. EXIT...{CRst}\n")
        return 1
    target_dir = os.path.abspath(target_dir)
    if not os.path.exists(target_dir):
        print(f"{FLYellow}Target directory does not exist. Creating...{CRst}")
        os.makedirs(target_dir, exist_ok=True)
    print(f"  -> target: {FLYellow}{target_dir}{CRst}")


    #============ 链接中保存的目标路径形式 ===========
    target_path_mode = TargetPathMode.ABSOLUTE
    if IS_WIN:
        has_relative_capable_link = (file_link_type == LinkType.SYMLINK) or (dir_link_type == LinkType.SYMLINKD)
    else:
        has_relative_capable_link = (file_link_type == LinkType.SYMLINK) or (dir_link_type == LinkType.SYMLINK)
    if has_relative_capable_link:
        path_mode_options = [
            MenuOption(["1"], "Absolute path", value=TargetPathMode.ABSOLUTE),
            MenuOption(["2"], "Relative path from link directory", value=TargetPathMode.RELATIVE),
        ]
        selected_relative_link_types = [
            lt for lt in (file_link_type, dir_link_type)
            if lt in (LinkType.SYMLINK, LinkType.SYMLINKD)
        ]
        supports_win_drive_root = (
            IS_WIN
            and len(selected_relative_link_types) > 0
            and all(lt == LinkType.SYMLINKD for lt in selected_relative_link_types)
        )
        if supports_win_drive_root:
            path_mode_options.append(
                MenuOption(["3"], r"Windows same-drive root-relative path (\target, SymlinkD only)", value=TargetPathMode.WIN_DRIVE_ROOT)
            )
        target_path_mode = Menu.select(
            path_mode_options,
            prompt="Choose target path style for symlinks",
            default_key="1",
        )
        if target_path_mode is None:
            target_path_mode = TargetPathMode.ABSOLUTE


    #============ 确认 ===========
    print(f"\n{FLYellow}--- Summary ---{CRst}")
    print(f"  Files     : {len(files)}, link type: {FLGreen}{file_link_type.name if file_link_type else 'N/A'}{CRst}")
    print(f"  Directories: {len(dirs)}, link type: {FLGreen}{dir_link_type.name if dir_link_type else 'N/A'}{CRst}")
    print(f"  Others    : {len(others)}")
    print(f"  Target    : {FLYellow}{target_dir}{CRst}")
    print(f"  Path mode : {FLYellow}{target_path_mode.name}{CRst}")
    if mirror_mode:
        print(f"  Mirror    : {FLYellow}mode {mirror_mode}{CRst}")
    confirm = input(f"\n{FLCyan}Proceed? (y/n, default y): {CRst}").strip().lower() or "y"
    if confirm != "y":
        print(f"{FLYellow}Cancelled. EXIT...{CRst}\n")
        return 0


    #============ 创建链接 ===========
    conflict_skip_all = False
    conflict_overwrite_all = False

    def resolve_target(source_path: str, link_type: LinkType) -> str:
        """返回链接中存储的目标路径（相对或绝对）"""
        if link_type == LinkType.HARDLINK or link_type == LinkType.JUNCTION:
            return os.path.abspath(source_path)
        if target_path_mode == TargetPathMode.RELATIVE:
            source_abs = os.path.abspath(source_path)
            if IS_WIN:
                source_drive = os.path.splitdrive(source_abs)[0].lower()
                target_drive = os.path.splitdrive(target_dir)[0].lower()
                if source_drive != target_drive:
                    print(f"  {FLYellow}Relative path skipped across drives:{CRst} {source_abs}")
                    return source_abs
                return os.path.relpath(source_abs, target_dir).replace("/", "\\")
            return os.path.relpath(source_abs, target_dir)
        if target_path_mode == TargetPathMode.WIN_DRIVE_ROOT:
            source_abs = os.path.abspath(source_path)
            if not IS_WIN or link_type != LinkType.SYMLINKD:
                return source_abs
            source_drive, source_tail = os.path.splitdrive(source_abs)
            target_drive = os.path.splitdrive(target_dir)[0]
            if source_drive.lower() != target_drive.lower():
                print(f"  {FLYellow}Root-relative path skipped across drives:{CRst} {source_abs}")
                return source_abs
            return source_tail.replace("/", "\\")
        return os.path.abspath(source_path)

    def link_name(source_path: str) -> str:
        return os.path.basename(os.path.abspath(source_path))

    def remove_existing_link_path(link_path: str) -> bool:
        if not os.path.lexists(link_path):
            return True
        try:
            if os.path.islink(link_path):
                try:
                    os.unlink(link_path)
                except IsADirectoryError:
                    os.rmdir(link_path)
            elif os.name == "nt" and getattr(os.path, "isjunction", lambda _p: False)(link_path):
                os.rmdir(link_path)
            elif os.path.isdir(link_path):
                print(f"  {FLRed}Refuse to overwrite real directory:{CRst} {link_path}")
                return False
            else:
                os.unlink(link_path)
            return True
        except Exception as e:
            print(f"  {FLRed}Failed to remove existing path:{CRst} {link_path} -> {e}")
            return False

    def handle_conflict(link_path: str) -> str:
        """处理已存在的链接/文件。返回 'skip' 'overwrite' 'skip_all' 'overwrite_all'"""
        nonlocal conflict_skip_all, conflict_overwrite_all
        if conflict_skip_all:
            return "skip"
        if conflict_overwrite_all:
            return "overwrite" if remove_existing_link_path(link_path) else "skip"

        print(f"\n{FLYellow}Conflict: {FLRed}{link_path}{FLYellow} already exists.{CRst}")
        choice = Menu.select(
            [
                MenuOption(["S"], "skip", value="skip"),
                MenuOption(["SA"], "skip all", value="skip_all"),
                MenuOption(["O"], "overwrite", value="overwrite"),
                MenuOption(["OA"], "overwrite all", value="overwrite_all"),
            ],
            prompt="Choose", default_key="S", inline=True, separator=False,
        )
        if choice == "skip_all":
            conflict_skip_all = True
            return "skip"
        elif choice == "overwrite_all":
            conflict_overwrite_all = True
            return "overwrite" if remove_existing_link_path(link_path) else "skip"
        elif choice == "overwrite":
            return "overwrite" if remove_existing_link_path(link_path) else "skip"
        else:
            return "skip"

    def create_link(source: str, link_path: str, link_type: LinkType) -> bool:
        """创建链接，返回是否成功"""
        link_dir = os.path.dirname(link_path)
        if link_dir and not os.path.exists(link_dir):
            os.makedirs(link_dir, exist_ok=True)

        if os.path.lexists(link_path):
            action = handle_conflict(link_path)
            if action.startswith("skip"):
                print(f"  {FGray}SKIP: {link_path}{CRst}")
                return False

        try:
            if IS_WIN:
                if link_type == LinkType.HARDLINK:
                    os.link(source, link_path)
                elif link_type == LinkType.JUNCTION:
                    subprocess.run(["cmd", "/c", "mklink", "/J", link_path, source],
                                check=True, capture_output=True, shell=False)
                elif link_type == LinkType.SYMLINKD:
                    os.symlink(source, link_path, target_is_directory=True)
                else:  # SYMLINK
                    os.symlink(source, link_path, target_is_directory=False)
            else:
                if link_type == LinkType.HARDLINK:
                    os.link(source, link_path)
                else:  # SYMLINK
                    os.symlink(source, link_path, target_is_directory=os.path.isdir(source))
            print(f"  {FLGreen}OK:{CRst} {link_path}")
            return True
        except Exception as e:
            print(f"  {FLRed}FAIL:{CRst} {link_path} -> {e}")
            return False


    succeed_count = 0
    fail_count = 0

    def process_path(source: str, link_type: LinkType):
        nonlocal succeed_count, fail_count
        resolved = resolve_target(source, link_type)
        name = link_name(source)
        link_path = os.path.join(target_dir, name)
        if create_link(resolved, link_path, link_type):
            succeed_count += 1
        else:
            fail_count += 1

    def process_mirror_flat(source_dir: str, file_lt: Optional[LinkType], dir_lt: Optional[LinkType]):
        """模式1：将文件夹内所有内容展平链接到目标"""
        nonlocal succeed_count, fail_count
        for entry in os.listdir(source_dir):
            entry_path = os.path.join(source_dir, entry)
            if os.path.islink(entry_path):
                print(f"  {FGray}SKIP (special): {entry_path}{CRst}")
                continue
            lt = dir_lt if os.path.isdir(entry_path) else file_lt
            if lt is None:
                print(f"  {FGray}SKIP (unsupported): {entry_path}{CRst}")
                continue
            resolved = resolve_target(entry_path, lt)
            link_path = os.path.join(target_dir, entry)
            if create_link(resolved, link_path, lt):
                succeed_count += 1
            else:
                fail_count += 1

    def process_mirror_recursive(source_dir: str, file_lt: Optional[LinkType]):
        """模式2：递归镜像目录结构，子目录创建为真实目录，文件创建为链接"""
        nonlocal succeed_count, fail_count
        for dirpath, dirnames, filenames in os.walk(source_dir):
            rel_dir = os.path.relpath(dirpath, source_dir)
            if rel_dir == ".":
                rel_dir = ""
            # 在目标下创建对应的真实目录（而非链接）
            target_subdir = os.path.join(target_dir, rel_dir)
            os.makedirs(target_subdir, exist_ok=True)
            for name in filenames:
                src = os.path.join(dirpath, name)
                if os.path.islink(src):
                    continue
                if file_lt is None:
                    print(f"  {FGray}SKIP (unsupported): {src}{CRst}")
                    continue
                resolved = resolve_target(src, file_lt)
                link_path = os.path.join(target_subdir, name)
                if create_link(resolved, link_path, file_lt):
                    succeed_count += 1
                else:
                    fail_count += 1


    print(f"\n{FLYellow}  -> creating links...{CRst}")

    if mirror_mode == 0:
        if files:
            assert file_link_type is not None
            for f in files:
                process_path(f, file_link_type)
        if dirs:
            assert dir_link_type is not None
            for d in dirs:
                process_path(d, dir_link_type)
    elif mirror_mode == 1:
        process_mirror_flat(mirror_source_dir, file_link_type, dir_link_type)
    elif mirror_mode == 2:
        process_mirror_recursive(mirror_source_dir, file_link_type)

    print(f"\n{FLGreen}Done. Succeed: {succeed_count}{CRst}, {FLRed}Failed: {fail_count}{CRst}, {FLYellow}Total: {succeed_count + fail_count}{CRst}\n")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
