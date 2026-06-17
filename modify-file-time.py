#!/usr/bin/env python3
from utils import *
import sys

import re
from typing import Final, Optional


# 文件/文件夹 时间修改器，支持加抖动

def main() -> int:
    Utils.print_banner("FILE TIME MODIFICATION TOOL")

    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
    FILE TIME MODIFICATION TOOL
    ===========================

    Usage:
      python {script_name}            enter interactive mode
      python {script_name} --help     show this help

    {FLYellow}Description:{CRst}
      Modify file/folder timestamps (created, modified, accessed).
      Supports random jitter (+Ns/-Ns/Ns format, in seconds).
      Supports backup and restore of original timestamps (JSON format).

    {FLYellow}Requirements:{CRst}
      No external dependencies. Uses ctypes for Windows file-time APIs.
    """)
        return 0




    g_path = ""
    g_isFollowSymlinks = False # 是否跟随符号链接修改时间，False 时修改链接本身的时间
    g_isRecursive = True
    # 时间格式："YYYY-MM-DD HH:MM:SS", "YYYY-MM-DD HH:MM:SS.zzz" 或 空字符串（不更改）
    g_timeFormatHint : Final = "YYYY-MM-DD HH:MM:SS, or YYYY-MM-DD HH:MM:SS.zzz (milliseconds), or empty to keep unchanged"
    # 随机抖动格式："+Ns", "-Ns", "Ns"（N为数字，单位为秒，不加符号为上下抖动）
    g_jitterFormatHint : Final = "+Ns, -Ns, Ns, or empty for no jitter. Unit is seconds; trailing 's' is optional."

    g_backupPath = None # 备份路径，Feature.BACKUP_TIMES 时使用
    g_restorePath = None # 恢复路径，Feature.RESTORE_TIMES 时使用
    # 备份文件 (JSON) 格式：
    # {
    # 	"文件路径1": {
    # 		"createdTime": "YYYY-MM-DD HH:MM:SS",
    # 		"modifiedTime": "YYYY-MM-DD HH:MM:SS",
    # 		"openedTime": "YYYY-MM-DD HH:MM:SS"
    # 	},
    # 	"文件路径2": {
    # 		...
    # 	}
    # }

    class Jitter:
        upperBound : Optional[datetime.timedelta] = None
        lowerBound : Optional[datetime.timedelta] = None

    def get_jittered_time(baseTime: datetime.datetime, jitter: Jitter) -> datetime.datetime:
        if jitter is None:
            return baseTime
        if jitter.lowerBound is None or jitter.upperBound is None:
            raise ValueError("Invalid jitter: lowerBound and upperBound must be provided")
        if jitter.lowerBound > jitter.upperBound:
            raise ValueError("Invalid jitter: lowerBound must be less than or equal to upperBound")
        jitter_seconds = (jitter.upperBound.total_seconds() - jitter.lowerBound.total_seconds()) * random.random() + jitter.lowerBound.total_seconds()
        jittered_time = baseTime + datetime.timedelta(seconds=jitter_seconds)
        return jittered_time

    class newTimeConfig:
        openedTime : Optional[datetime.datetime] = None
        createdTime : Optional[datetime.datetime] = None
        modifiedTime : Optional[datetime.datetime] = None

        openedTimeJitter : Optional[Jitter] = None
        createdTimeJitter : Optional[Jitter] = None
        modifiedTimeJitter : Optional[Jitter] = None


    class FileTimeInfo:
        openedTime : Optional[datetime.datetime] = None
        createdTime : Optional[datetime.datetime] = None
        modifiedTime : Optional[datetime.datetime] = None



    g_newTimeConfig = newTimeConfig()

    class Feature(enum.Enum):
        MODIFY_TIMES = 1
        BACKUP_TIMES = 2
        RESTORE_TIMES = 3
        SHOW_TIMES = 4
    g_feature : Feature = Feature.MODIFY_TIMES

    def parse_dt(s: str) -> Optional[datetime.datetime]:
        """
        Parse:
          - "YYYY-MM-DD HH:MM:SS"
          - "YYYY-MM-DD HH:MM:SS.zzz"   (zzz = milliseconds)
        Return naive datetime in local time semantics.
        """
        if s is None:
            return None
        s = s.strip()
        if s == "":
            return None

        # Fast path: no fractional seconds
        if "." not in s:
            return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")

        # Fractional seconds: pad/truncate to microseconds (6 digits)
        main, frac = s.split(".", 1)
        # keep only digits in fractional part (optional, stricter: validate frac.isdigit())
        frac_digits = "".join(ch for ch in frac if ch.isdigit())
        if frac_digits == "":
            raise ValueError(f"Invalid fractional seconds: {s}")

        frac6 = (frac_digits + "000000")[:6]  # pad right to 6, then cut
        s_norm = f"{main}.{frac6}"
        return datetime.datetime.strptime(s_norm, "%Y-%m-%d %H:%M:%S.%f")


    def _format_dt(dt: Optional[datetime.datetime], isFormatZZZ : bool = False) -> Optional[str]:
        if dt is None:
            return None
        if(isFormatZZZ):
            return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] # keep milliseconds only
        else:
            return dt.strftime("%Y-%m-%d %H:%M:%S")

    def parse_jitter(s: str) -> Optional[Jitter]:
        """
        Parse jitter:
          - "" -> None
          - "+Ns" -> [0, +N]
          - "-Ns" -> [-N, 0]
          - "Ns"  -> [-N, +N]
        Unit is seconds; trailing 's' is optional.
        """
        if s is None:
            return None
        s = s.strip()
        if s == "":
            return None

        m = re.match(r"^([+-]?)(\d+)\s*s?$", s)
        if not m:
            raise ValueError(f"Invalid jitter format: {s}")

        sign = m.group(1)
        n = int(m.group(2))
        d = datetime.timedelta(seconds=n)

        j = Jitter()
        if sign == "+":
            j.lowerBound = datetime.timedelta(seconds=0)
            j.upperBound = d
        elif sign == "-":
            j.lowerBound = -d
            j.upperBound = datetime.timedelta(seconds=0)
        else:
            j.lowerBound = -d
            j.upperBound = d
        return j




    if sys.platform.startswith("win"):
        class _FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_uint32),
                        ("dwHighDateTime", ctypes.c_uint32)]

        def _dt_to_filetime_utc(dt: datetime.datetime) -> _FILETIME:
            # Convert datetime -> Windows FILETIME (100-ns since 1601-01-01 UTC)
            if dt.tzinfo is None:
                # treat naive as local time to match typical user expectation
                dt = dt.astimezone()
            dt_utc = dt.astimezone(datetime.timezone.utc)
            ft = int(dt_utc.timestamp() * 10_000_000) + 116444736000000000
            return _FILETIME(ft & 0xFFFFFFFF, (ft >> 32) & 0xFFFFFFFF)

        def _set_creation_time_windows(path: str, created: datetime.datetime, follow_symlinks: bool) -> None:
            k32 = getattr(ctypes, "windll").kernel32

            FILE_WRITE_ATTRIBUTES = 0x0100
            FILE_SHARE_READ  = 0x00000001
            FILE_SHARE_WRITE = 0x00000002
            FILE_SHARE_DELETE= 0x00000004
            OPEN_EXISTING = 3
            FILE_FLAG_BACKUP_SEMANTICS   = 0x02000000  # required for directories
            FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000  # open symlink itself

            flags = FILE_FLAG_BACKUP_SEMANTICS
            if not follow_symlinks:
                flags |= FILE_FLAG_OPEN_REPARSE_POINT

            handle = k32.CreateFileW(
                path,
                FILE_WRITE_ATTRIBUTES,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                None,
                OPEN_EXISTING,
                flags,
                None
            )
            INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
            if handle == INVALID_HANDLE_VALUE:
                raise OSError(f"CreateFileW failed for: {path}")

            try:
                ft_c = _dt_to_filetime_utc(created)
                if not k32.SetFileTime(handle, ctypes.byref(ft_c), None, None):
                    raise OSError(f"SetFileTime failed for: {path}")
            finally:
                k32.CloseHandle(handle)



    class FileNode():
        path : str
        timeInfo : FileTimeInfo
        shouldWriteCreatedTime : bool

        def __init__(self, path:str):
            self.path = path
            self.shouldWriteCreatedTime = False
            self.load_file_time_info()

        def load_file_time_info(self) -> None:
            timeInfo = FileTimeInfo()
            if(os.path.lexists(self.path) == False):
                print(f"{FLRed}File does not exist: {self.path}{CRst}")
                return None
            stat_info = os.stat(self.path, follow_symlinks=g_isFollowSymlinks)
            # st_birthtime exists on macOS and some BSDs; it is typically missing on Linux.
            birth = getattr(stat_info, "st_birthtime", None)
            timeInfo.createdTime = datetime.datetime.fromtimestamp(birth) if birth is not None else None
            timeInfo.modifiedTime = datetime.datetime.fromtimestamp(stat_info.st_mtime)
            timeInfo.openedTime = datetime.datetime.fromtimestamp(stat_info.st_atime)
            self.timeInfo = timeInfo

        def print_times(self):
            if(os.path.lexists(self.path) == False):
                print(f"{FLRed}File does not exist: {self.path}{CRst}")
                return
            extra = f"{FLYellow}[LINK]{CRst}" if(os.path.islink(self.path)) else ""
            if(os.path.isfile(self.path)):
                print(f"{extra}{FLGreen}File: {self.path}{CRst}")
            elif(os.path.isdir(self.path)):
                print(f"{extra}{FLCyan}Directory: {self.path}{CRst}")
            created_str = self.timeInfo.createdTime if self.timeInfo.createdTime is not None else "(N/A)"
            print(f"  -> Created Time: {FLCyan}{created_str}{CRst}")
            print(f"  -> Modified Time: {FLCyan}{self.timeInfo.modifiedTime}{CRst}")
            print(f"  -> Opened Time: {FLCyan}{self.timeInfo.openedTime}{CRst}")

        def print_path(self):
            extra = ""
            path = self.path
            if(os.path.islink(path)):
                extra = f"{FLYellow}[L]{CRst}"
            if(os.path.isfile(path)):
                extra = f"{extra}{FLGreen}[F]{CRst}"
            elif(os.path.isdir(path)):
                extra = f"{extra}{FLCyan}[D]{CRst}"
            print(f"   -> {extra}{path}")

        def apply_new_time(self, timeConfig: newTimeConfig) -> None:
            # Apply each field independently; empty input means "keep unchanged".
            if timeConfig.openedTime is not None:
                j = timeConfig.openedTimeJitter
                self.timeInfo.openedTime = get_jittered_time(timeConfig.openedTime, j) if j is not None else timeConfig.openedTime
            if timeConfig.modifiedTime is not None:
                j = timeConfig.modifiedTimeJitter
                self.timeInfo.modifiedTime = get_jittered_time(timeConfig.modifiedTime, j) if j is not None else timeConfig.modifiedTime
            if timeConfig.createdTime is not None:
                j = timeConfig.createdTimeJitter
                self.timeInfo.createdTime = get_jittered_time(timeConfig.createdTime, j) if j is not None else timeConfig.createdTime
                self.shouldWriteCreatedTime = True

        def write_file_time_info(self) -> bool:
            if(os.path.lexists(self.path) == False):
                print(f"{FLRed}File does not exist: {self.path}{CRst}")
                return False

            atime = self.timeInfo.openedTime.timestamp() if self.timeInfo.openedTime is not None else None
            mtime = self.timeInfo.modifiedTime.timestamp() if self.timeInfo.modifiedTime is not None else None
            ret : bool = True
            if(atime is None):
                atime = os.stat(self.path, follow_symlinks=g_isFollowSymlinks).st_atime
            if(mtime is None):
                mtime = os.stat(self.path, follow_symlinks=g_isFollowSymlinks).st_mtime

            if (atime is not None) and (mtime is not None):
                try:
                    os.utime(self.path, (atime, mtime), follow_symlinks=g_isFollowSymlinks)
                except Exception as e:
                    print(f"{FLRed}Failed to set modified and accessed time for file: {self.path}. Error: {e}{CRst}")
                    ret = False
            else:
                print(f"{FLRed}Invalid time info for file: {self.path}. openedTime and modifiedTime must be provided.{CRst}")
                ret = False

            if self.shouldWriteCreatedTime and self.timeInfo.createdTime is not None:
                if sys.platform.startswith("win"):
                    try:
                        _set_creation_time_windows(self.path, self.timeInfo.createdTime, follow_symlinks=g_isFollowSymlinks)
                    except Exception as e:
                        print(f"{FLRed}Failed to set creation time for file: {self.path}. Error: {e}{CRst}")
                        return False
                else:
                    print(f"{FLYellow}Note: creation time is not supported on this platform; ignoring for: {self.path}{CRst}")

            return ret



    def load_file_nodes_from_directory(directory:str, recursive:bool) -> list[FileNode]:
        fileNodes = []
        if not os.path.lexists(directory):
            print(f"{FLRed}Directory does not exist: {directory}{CRst}")
            return fileNodes
        if(os.path.isfile(directory)):
            fileNodes.append(FileNode(directory))
            return fileNodes
        fileNodes.append(FileNode(directory))
        if recursive:
            for root, dirs, files in os.walk(directory):
                for file in files:
                    file_path = os.path.join(root, file)
                    fileNodes.append(FileNode(file_path))
                for dir in dirs:
                    dir_path = os.path.join(root, dir)
                    fileNodes.append(FileNode(dir_path))
        else:
            for entry in os.scandir(directory):
                if entry.is_file():
                    fileNodes.append(FileNode(entry.path))
                elif entry.is_dir():
                    fileNodes.append(FileNode(entry.path))
        return fileNodes


    def backup_file_times(fileNodes: list[FileNode], backupPath: str) -> bool:
        backupData = {}
        for node in fileNodes:
            if node.timeInfo is None:
                node.load_file_time_info()
            isFormatZZZ = True
            backupData[node.path] = {
                "createdTime": _format_dt(node.timeInfo.createdTime, isFormatZZZ),
                "modifiedTime": _format_dt(node.timeInfo.modifiedTime, isFormatZZZ),
                "openedTime": _format_dt(node.timeInfo.openedTime, isFormatZZZ)
            }
        try:
            with open(backupPath, "w", encoding="utf-8") as f:
                json.dump(backupData, f, ensure_ascii=False, indent=4)
            print(f"{FLGreen}File times backed up successfully to: {backupPath}{CRst}")
            return True
        except Exception as e:
            print(f"{FLRed}Failed to backup file times to: {backupPath}. Error: {e}{CRst}")
            return False


    def restore_file_times(backupPath : str) -> int:
        try:
            with open(backupPath, "r", encoding="utf-8") as f:
                backupData = json.load(f)
        except Exception as e:
            print(f"{FLRed}Failed to read backup file: {backupPath}. Error: {e}{CRst}")
            return 0
        succeedCnt = 0
        for path, times in backupData.items():
            if not os.path.lexists(path):
                print(f"{FLRed}File does not exist: {path}{CRst}")
                continue
            node = FileNode(path)
            try:
                node.timeInfo.createdTime = parse_dt(times.get("createdTime"))
                node.timeInfo.modifiedTime = parse_dt(times.get("modifiedTime"))
                node.timeInfo.openedTime = parse_dt(times.get("openedTime"))
                node.shouldWriteCreatedTime = node.timeInfo.createdTime is not None
            except ValueError as e:
                print(f"{FLRed}Invalid time format in backup for {path}: {e}{CRst}")
                continue
            isSucceed = node.write_file_time_info()
            if isSucceed:
                succeedCnt += 1
                # print(f"{FLGreen}Restored times for file/folder: {path}{CRst}")
                pass
            else:
                print(f"{FLRed}Failed to restore times for file/folder: {path}{CRst}")
                continue

        return succeedCnt




    #============ 用户交互 ===========

    featureInt = Menu.select(
        [
            MenuOption(["1"], "Modify times", value=1),
            MenuOption(["2"], "Backup times", value=2),
            MenuOption(["3"], "Restore times", value=3),
            MenuOption(["4"], "Show times", value=4),
        ],
        prompt="Select feature",
    )
    if featureInt is None:
        Utils.print_exit_message("Bye.")
        return 0
    g_feature = Feature(featureInt)

    if(g_feature == Feature.MODIFY_TIMES) or g_feature == Feature.BACKUP_TIMES:
        g_path = Input.resolve_input_path(".", prompt="Enter file/directory path to modify time", path_type="any")
        if(os.path.isdir(g_path)):
            isRecursiveStr = input(f"{FLCyan}The specified path is a directory. Modify time for files in subdirectories as well? (y/n, default y): {CRst}") or "y"
            g_isRecursive = isRecursiveStr.strip().lower() == 'y'
        print(f" path: {g_path}")

    if(g_feature == Feature.MODIFY_TIMES) or g_feature == Feature.BACKUP_TIMES or g_feature == Feature.SHOW_TIMES:
        followSymlinksStr = input(f"{FLCyan}Follow symbolic links when reading/modifying time? (y/n, default n): {CRst}") or "n"
        g_isFollowSymlinks = followSymlinksStr.strip().lower() == 'y'

    if(g_feature == Feature.MODIFY_TIMES):
        modifyTogetherStr = input(f"{FLCyan}Modify created, modified and opened time together to the same value? (y/n, default n): {CRst}") or "n"
        modifyTogether = modifyTogetherStr.strip().lower() == 'y'

        if(not modifyTogether):
            print(f"{FLYellow}Enter new times for created, modified and opened time separately. {CRst} Format: {g_timeFormatHint}")
            createdTimeStr = input(f"{FLYellow}Enter new created time: {CRst}")
            modifiedTimeStr = input(f"{FLYellow}Enter new modified time: {CRst}")
            openedTimeStr = input(f"{FLYellow}Enter new opened time: {CRst}")
            try:
                g_newTimeConfig.createdTime = parse_dt(createdTimeStr)
                g_newTimeConfig.modifiedTime = parse_dt(modifiedTimeStr)
                g_newTimeConfig.openedTime = parse_dt(openedTimeStr)
            except ValueError as e:
                print(f"{FLRed}Invalid time format: {e}. EXIT...{CRst}\n")
                return 1
            print(f"{FLYellow}Enter jitter for created, modified and opened time separately. {CRst} Format: {g_jitterFormatHint}")
            createdJitterStr = input(f"{FLCyan}Enter jitter for created time: {CRst}")
            modifiedJitterStr = input(f"{FLCyan}Enter jitter for modified time: {CRst}")
            openedJitterStr = input(f"{FLCyan}Enter jitter for opened time: {CRst}")
            try:
                g_newTimeConfig.createdTimeJitter = parse_jitter(createdJitterStr)
                g_newTimeConfig.modifiedTimeJitter = parse_jitter(modifiedJitterStr)
                g_newTimeConfig.openedTimeJitter = parse_jitter(openedJitterStr)
            except ValueError as e:
                print(f"{FLRed}Invalid jitter format: {e}. EXIT...{CRst}\n")
                return 1

        else:
            print(f"{FLYellow}Enter new time for created, modified and opened time together. {CRst} Format: {g_timeFormatHint}")
            newTimeStr = input(f"{FLYellow}time: {CRst}")
            try:
                newTime = typing.cast(datetime.datetime, parse_dt(newTimeStr))
                g_newTimeConfig.createdTime = newTime
                g_newTimeConfig.modifiedTime = newTime
                g_newTimeConfig.openedTime = newTime
                print(f"{FLYellow}Enter jitter for created, modified and opened time together. {CRst} Format: {g_jitterFormatHint}")
                newJitterStr = input(f"{FLCyan}jitter: {CRst}")
                newJitter = typing.cast(Jitter, parse_jitter(newJitterStr))
                g_newTimeConfig.createdTimeJitter = newJitter
                g_newTimeConfig.modifiedTimeJitter = newJitter
                g_newTimeConfig.openedTimeJitter = newJitter
            except ValueError as e:
                print(f"{FLRed}Invalid time or jitter format: {e}. EXIT...{CRst}\n")
                return 1

    elif g_feature == Feature.BACKUP_TIMES:
        _default_backup = os.path.join(os.path.dirname(g_path) or ".", "backup_times.json")
        g_backupPath = Input.resolve_output_path(_default_backup, prompt="Enter backup JSON file path", path_type="file")
    elif g_feature == Feature.RESTORE_TIMES:
        g_restorePath = Input.resolve_input_path(
            "backup_times.json",
            prompt="Enter backup JSON file path to restore times",
            path_type="file",
        )
    elif g_feature == Feature.SHOW_TIMES:
        g_path = Input.resolve_input_path(".", prompt="Enter file/directory path to show time", path_type="any")

        node = FileNode(g_path)
        if(os.path.isdir(g_path)):
            is_show_recursively = input(f"Path `{g_path}` is a directory, recursively showing times for contained files/directories? (y/n, default y): ") or "y"
            if is_show_recursively.strip().lower() == 'y':
                nodes = load_file_nodes_from_directory(g_path, recursive=True)
                for n in nodes:
                    n.print_times()
                print(f"{FLGreen}Total {len(nodes)} files/directories shown.{CRst}")
                return 0

        node.print_times()
        return 0



    #============ 代码主体部分 ===========

    g_fileNodes = []
    if(g_feature == Feature.MODIFY_TIMES) or g_feature == Feature.BACKUP_TIMES:
        g_fileNodes = load_file_nodes_from_directory(g_path, g_isRecursive)

    if(g_feature == Feature.MODIFY_TIMES):
        for node in g_fileNodes:
            node.print_path()
            node.apply_new_time(g_newTimeConfig)
            node.write_file_time_info()
        print(f"{FLGreen}File times modified successfully for {len(g_fileNodes)} files/directories.{CRst}")

    elif g_feature == Feature.BACKUP_TIMES:
        if isinstance(g_backupPath, str):
            backup_file_times(g_fileNodes, g_backupPath)
            print(f"{FLGreen}File times backed up successfully for {len(g_fileNodes)} files/directories.{CRst}")

    elif g_feature == Feature.RESTORE_TIMES:
        if isinstance(g_restorePath, str):
            succeedCnt = restore_file_times(g_restorePath)
            print(f"{FLGreen}File times restored successfully for {succeedCnt} files/directories.{CRst}")

    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
