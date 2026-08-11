# Personal Scripts

[English](./README.md)

GitHub: https://github.com/BH2WFR/PersonalScripts

> 本项目大部分具体代码由 **DeepSeek V4 Pro** 模型在我的反复迭代修改下通过 vibe coding 生成。

跨平台日常实用脚本合集 — PDF 处理、文件链接、视频下载、系统工具等。

大部分脚本支持交互模式和命令行参数。使用 `python <脚本名>.py --help` 查看用法详情。

## 快速开始

```bash
# 交互模式：列出支持的脚本，按数字或名称选择
./run-script.sh                                # Linux/macOS
.\run-script.ps1                               # Windows
python run-script.py                           # 全平台

# 直接运行指定脚本（参数透传）
./run-script.sh <脚本名> [参数...]              # Linux/macOS
.\run-script.ps1 <脚本名> [参数...]             # Windows
python run-script.py <脚本名> [参数...]         # 全平台

# 仅列出可用脚本
./run-script.sh --list                         # Linux/macOS
.\run-script.ps1 --list                        # Windows
python run-script.py --list                    # 全平台

# 将任意 Python 脚本编译为独立可执行文件（Nuitka / PyInstaller）
python compile-script.py                        # 全平台
```

**启动器特性：**

- 交互式选择支持**数字**或**脚本名称**（如 `15`、`macos/ntfs-3g-utils`）
- 数字/名称后的参数**透传**给目标脚本（如 `15 --help`、`macos/screen-utils --list`）
- 启动时打印 OS 版本、Python 路径与版本、conda 环境、pwsh/bash 可用性
- 输入 `rclone-sync` 这样的裸脚本名时，会按文件名递归搜索所有可用子目录；若不同路径或扩展名产生多个匹配，启动器会警告并打印全部候选，用户按数字选择后，原参数继续透传
- 当 `launcher.test.enabled` 为 `true` 时，配置的测试目录会显示为独立 `Test` 分组并参与裸名查找；可用 `test/<名称>` 或 `@test:<名称>` 精确指定
- 从 `launcher-config.yaml` 指定的主目录发现脚本（默认为 `tools`）
- 从 `launcher-config.yaml` 读取 Gitignore 风格通配规则，支持 `*`、`**`、`?`、字符范围及 `!` 反向规则
- 平台相关过滤规则配置在 `ignore-list.platform-specific` 中
- 解释器感知：无 `bash` 时隐藏 `.sh` 脚本；无 `pwsh` 时隐藏 `.ps1` 脚本
- 列出解释器支持的所有扩展名；Windows 找到 Bash 时，即使存在同名 `.py` 也会列出 `.sh`
- 自动检测 Python：优先使用 `conda info --base`，再尝试已知路径，最后回退到 `python3`
- **可配置高亮**：`launcher-config.yaml` 中的 `script-name-highlight-pattern` 和 `folder-name-highlight-pattern` 将 ANSI 颜色名称映射到正则表达式列表
- **可配置脚本类型和颜色**：扩展名、默认颜色、目录颜色及附加分组标题颜色均由 YAML 定义
- **`ZL_SCRIPT_ADDITIONAL_PATH`** 用于发现附加目录，环境变量名本身也可配置。多个目录使用平台路径分隔符分隔（Windows 为 `;`，macOS/Linux 为 `:`）；相对路径以项目根目录为基准。每个目录显示为 `─── Additional [N] ───`（N 从 1 开始），并应用相同的配置化忽略规则。
  配合 **`@N:` 前缀** 可精确指定脚本来源：`@0:` = 主目录，`@1:` = 第一个附加目录（对应 `Additional [1]`），依此类推。裸名递归搜索所有分组；`@N:` 将相同匹配规则限制到指定分组。多个有效匹配会以带编号的 `@N:` 路径列出。CLI 同样可用（如 `python run-script.py @1:test.py`）
- `compile-script.py` 可将项目中任意 Python 脚本编译为独立可执行文件，支持 Nuitka 或 PyInstaller（均为 `--onedir`/`--standalone` 模式，不自解压以避免磨损硬盘）

### 启动器配置

`launcher-config.yaml` 统一定义启动器路径、支持的脚本类型、颜色、高亮 pattern 和忽略规则。配置中的相对路径以项目根目录为基准；忽略规则相对于每个扫描根目录进行匹配：

可选且被 Git 忽略的 `launcher-config.patch.yaml` 存在时，会深度合并覆盖主配置：嵌套 mapping 递归合并，标量和列表完整替换；文件不存在时不作任何覆盖。

```yaml
launcher:
    script-root: "tools"
    test:
        enabled: true
        test-root: "test"
    additional-path-env: "ZL_SCRIPT_ADDITIONAL_PATH"
script-name-highlight-pattern:
    FLYellow:
        - "\\brclone\\b"
folder-name-highlight-pattern:
    FLGreen:
        - "^windows/"
ignore-list:
    all-platforms:
        - "**/__pycache__/"
    platform-specific:
        windows:
            - "macos/"
```

颜色名称通过 `Utils.resolve_ansi_color()` 转换。颜色、正则或 YAML 结构无效时，启动器会报告配置错误并停止；配置的脚本目录不存在时同样拒绝运行。

---

## 脚本列表

### PDF 工具

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/document-processing/pdf-compress.py` | PDF 压缩工具，支持 Ebook（标准）和 Custom（自定义 DPI/质量）模式 | 跨平台。`ghostscript` |
| `tools/document-processing/pdf-decrypt.py` | 解密受密码保护的 PDF（含仅权限保护），保留完整文档结构 | 跨平台。`pypdf` |
| `tools/document-processing/pdf-bookmarks-add.py` | 用于扫描版 PDF 书籍：先将目录页截图发给多模态 LLM（如 Qwen3-VL）生成 JSON（含页码/层级/编号/标题），再用此脚本将 JSON 解析并写入 PDF 书签 | 跨平台。`pypdf` |
| `tools/document-processing/document-screenshot.py` | 自动截图 PDF 文档（模拟 PgDn 翻页 + 鼠标点击），适用于 DRM 保护的或加密 USB 中的 PDF | 仅 **macOS**。`mss`、`pynput`、`Pillow` |

### 视频下载

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/download/download-bilibili.py` | B 站视频下载器（画质/仅音频/字幕/弹幕/多 API） | 跨平台。`BBDown`、`ffmpeg`、`aria2`（可选） |
| `tools/download/download-yt.py` | YouTube 视频下载器（画质/音频/字幕/cookies/播放列表） | 跨平台。`yt-dlp`、`ffmpeg`、`deno`（可选） |
| `tools/download/download-m3u8.py` | m3u8/HLS 流媒体下载器，支持自定义请求头 | 跨平台。`yt-dlp`、`ffmpeg` |

### 视频/图片编辑

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/multimedia/ffmpeg-crop-video.py` | 按时间段裁切视频（非画面裁剪） | 跨平台。`ffmpeg` |
| `tools/research/batch-crop-images.py` | 批量裁剪图片，交互式选择 ROI 区域 | 跨平台。`opencv-python`、`numpy` |

### 文件系统与链接

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/filesystem/link-create.py` | 跨平台符号链接/硬链接创建（Windows: SymlinkD, Junction；Linux/macOS: Symlink, Hardlink）。支持相对路径、镜像模式、冲突处理 | 跨平台 |
| `tools/filesystem/link-scan.py` | 递归扫描目录，打印所有符号链接、目录软链接（symlinkd）、Junction 和硬链接。检测死链（目标不存在），自动修复或删除；Windows 下可将错误指向目录的文件软链接转换为 symlinkd | 跨平台 |
| `tools/filesystem/link-fix-to-symlinkd-windows.py` | Windows 专用：将指向目录的文件软链接（file symlink）**修复**为正确的**目录软链接**（symlinkd / SYMLINKD）。Windows 的文件软链接与目录软链接是两种不同的重解析点类型，部分工具可能误建文件软链接指向目录，导致遍历失败 | 仅 **Windows** |
| `tools/filesystem/openssl-file-hash.py` | 对多行输入的多个文件调用 OpenSSL 计算一种或多种哈希。输入前列出当前 OpenSSL 实际支持的常用算法，再接受 `sha256,md5` 等逗号组合；文件软链接会跟随目标并明确显示，文件夹、失效链接和不存在的路径会被跳过，结果按文件分组输出 | 跨平台。必须安装 `openssl` |
| `tools/filesystem/check-filename-overlong.py` | 按 UTF-8 编码统计字节长度，截断超过指定字节数（默认 143，适配群晖加密文件夹）的文件名。截断时保留扩展名，若发生重名则在扩展名前自动加 `_1`、`_2` 等后缀 | 跨平台 |
| `tools/filesystem/remove-os-junk-files.py` | 递归删除系统生成的垃圾文件（`.DS_Store`、`__MACOSX__`、`Thumbs.db` 等） | 跨平台 |
| `tools/filesystem/modify-file-time.py` | 修改文件/文件夹时间戳（创建/修改/访问时间），支持随机抖动 | 跨平台 |
| `tools/filesystem/batch-add-chmod-x.sh` | 递归查找指定扩展名（默认 `.py`/`.sh`）的文件并添加 `chmod +x` 可执行权限，自动 sudo 提权 | Linux/macOS。`bash`、`sudo`（系统自带） |
| `tools/git-batch-add-chmod-x.ps1` | 将 git 暂存区中 `.py`/`.sh` 文件通过 `git update-index --chmod=+x` 标记为可执行，方便跨平台开发时 Windows 端提交的文件在 Linux/macOS 上 clone 后自带 +x 权限 | Windows。`PowerShell`、`git` |

### 系统与网络

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/disk-smart-info.py` | 跨平台 SMART 磁盘健康信息查看器，列出 SMART 磁盘并显示详细属性 | 跨平台。`smartmontools` |
| `tools/network/tailscale-restart-accept-routes.py` | 通过切换 `--accept-routes` 开关重启 Tailscale 子网路由 | 跨平台。`tailscale` |
| `tools/network/rclone-sync.py` | 基于 YAML 的 rclone 同步任务运行器。支持可复用 profile、按机器过滤 sub-task、交互式主机/方向选择、修改时间比较、dry-run、pre-check，以及在 rclone 操作期间用 Ctrl+C 取消（交互模式返回任务菜单；使用 `--task` 时退出码 130） | 跨平台。`rclone`、`PyYAML` |
| `tools/network/upload-ipaddress.py` | 收集网络信息（`ipconfig`/`ip addr`）并上传至腾讯云 COS S3，方便远程访问。凭据来自环境变量：`ZL-IP-ADDRESS-S3-BUCKET`、`ZL-IP-ADDRESS-S3-ENDPOINT`、`ZL-IP-ADDRESS-S3-ID`、`ZL-IP-ADDRESS-S3-SECRET` | 跨平台。`boto3` |
| `tools/macos/ntfs-3g-utils.py` | macOS 专用：交互式 NTFS 分区管理。扫描 NTFS 分区后提供三种操作：ntfs-3g 读写挂载、系统只读挂载、弹出磁盘。读写挂载支持自动检测已有挂载点并创建备选目录 | **仅 macOS**。`brew install ntfs-3g macfuse` |
| `tools/macos/screen-utils.py` | macOS 专用（Apple Silicon）：显示器管理 — 旋转、分辨率、亮度（内建 + 外接显示器 DDC/CI）、色彩模式诊断、外接显示器强制 RGB 输出覆写。特色功能：MacBook 连接外接显示器时，可一键开关笔记本自带屏幕（`--toggle-built-in`），关闭时会校验外接显示器存在、打开时自动恢复过低亮度。**RGB 覆写**：修补 EDID 清除 YCbCr 标志，将系统显示覆写写入 `/Library/Displays/Contents/Resources/Overrides/`（需 sudo）；重启后持久保留，重新插拔显示器生效 | **仅 macOS**（Apple Silicon）；可选 `pyobjc-framework-Cocoa` |
| `tools/power-current.py` | 跨平台充电器与电池遥测查看器。macOS 使用 `ioreg`，Windows 使用 PowerShell CIM/WMI，Linux 使用 `/sys/class/power_supply`。部分字段可能因固件/驱动限制不可用 | 跨平台 |
| `tools/macos/remove-quarantine.py` | macOS 专用：移除文件/文件夹的 quarantine 隔离属性（支持递归批量，可选清 provenance，逐文件计数） | **仅 macOS**。使用 `xattr`（系统自带） |
| `tools/windows/clear-android-rndis-record.py` | 清理 Windows 注册表中残留的 Android USB 网络共享/RNDIS 记录。列出所有网络连接，根据网卡元数据标记 USB Remote NDIS 记录，确认后删除选中的注册表记录。支持 `--force` 和 `--match` 额外正则匹配 | **仅 Windows** |
| `tools/windows/file-association.py` | 交互式 Windows 文件关联管理器。列出某扩展名在各注册表入口中声明的打开方式，解析启动命令并检查可执行文件；可按数字精确删除某个来源项，删除后自动重新列出。添加功能支持推荐的 Default Apps + Open With、仅 OpenWithProgids、仅 Applications/SupportedTypes 三种入口，会检查 EXE，默认参数为 `"%1"`，可选择当前用户或提权后的系统范围，添加后同样重新列出；不会写入受 Windows 保护的 UserChoice 默认项 | **仅 Windows**。Python 标准库（`winreg`、`ctypes`） |
| `tools/windows/clear-all-event-logs.py` | 使用 `wevtutil` 枚举并在管理员权限下依次清除全部已注册的 Windows Event Log 通道。默认要求确认，`--force` 可跳过确认；单个通道失败时继续执行并在结尾报告准确的成功/失败数量。清除不可恢复，不会停止后续日志记录，Windows 也可能立即产生新事件 | **仅 Windows**。系统内置 `wevtutil` |
| `tools/windows/clear-privacy.py` | 清除 Windows 隐私痕迹（资源管理器历史、事件日志、DNS 缓存、浏览器数据、凭据、临时文件等），支持逐项确认。**免责声明：使用风险自负。** | **仅 Windows**。系统自带工具；可选 `scoop install sudo gsudo` |
| `tools/windows/clear-recycle-bin.py` | 清空 Windows 回收站（逐盘符）。Phase 1 调用 shell API（`SHEmptyRecycleBinW`）正常清空；Phase 2 对残余项（如 OneDrive"始终保存到本地"文件夹）直接遍历 `$Recycle.Bin` 强力删除。回收站内的重解析点（junction/symlink）仅删除链接本身，不会跟随到目标。支持 `--force-run` 无交互自动执行 | **仅 Windows** |
| `tools/windows/show-screen-resolution.py` | 通过 Windows API 显示显示器分辨率和屏幕信息 | **仅 Windows** |
| `tools/macos/clear-privacy.py` | 清除 macOS 隐私痕迹（最近项目、访达状态、Shell 历史、浏览器数据、缓存、日志等），支持逐项确认。**免责声明：使用风险自负。** | **仅 macOS**。系统自带工具；可选 `brew install trash` |
| `tools/network/webserver-run.py` | 将本地文件夹（或含 index.html 的网页目录）映射为本地 HTTP 服务。支持交互模式（目录/绑定地址/端口）或 CLI（`--dir`、`--bind`、`--port`），基于 Python 内置 `http.server` 的多线程服务 | 跨平台 |

### 实用工具

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/parse-unicode-string.py` | 解析并显示 Unicode 字符信息（序号、字符、十六进制、十进制、说明），特殊字符彩色标注。支持 `--clip`（剪贴板读取）、`--pause`（回车后退出）、`--help` | 跨平台；Linux 剪贴板需 `wl-paste` 或 `xclip` |
| `tools/research/npy-viewer.py` | `.npy`/`.npz` 文件交互式查看器（1D 折线/柱状/散点图，2D 热力图/曲面图） | 跨平台。`numpy`、`matplotlib`、`plotly` |
| `tools/research/pattern-generator.py` | 交互式结构光投影图案生成器。支持正弦条纹图案和 standard Gray code 序列，可选生成反码图案 | 跨平台。`opencv-python`、`numpy` |
| `tools/macos/script-to-app.py` | 创建 macOS `.app` 包，将任意 Python 脚本包装为可双击启动的应用程序，用于通过访达"打开方式"关联文件类型 | **仅 macOS** |
| `tools/windows/script-to-app.py` | 创建 Windows `.cmd` 启动器，将任意 Python 脚本安装到 `Program Files`。自动检测 Python（conda/系统），接收打开的文件路径作为参数，支持"打开方式"关联文件类型 | **仅 Windows** |

### 启动器与编译

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `run-script.py` | 统一脚本启动器。从 `launcher-config.yaml` 加载配置并支持可选个人 patch；提供可配置 Test 分组、裸名递归查找、重名选择、附加目录以及 `@test:`、`@N:` 定位 | 跨平台。`Python 3.13+`、`PyYAML`、`pathspec` |
| `run-script.sh` | Bash 启动器（启动器的启动器）：查找 Python 解释器后将所有参数透传给 `run-script.py` | Linux/macOS。`bash`、`python3` |
| `run-script.ps1` | PowerShell 启动器（启动器的启动器）：查找 Python 解释器后将所有参数透传给 `run-script.py` | Windows。`PowerShell`、`python` |
| `compile-script.py` | 交互式编译器：选择任意 Python 脚本，通过 Nuitka 或 PyInstaller 打包为独立可执行文件（均为 `--onedir`/`--standalone`，不自解压以避免磨损 SSD） | 跨平台。`pip install nuitka` 和/或 `pip install pyinstaller` |

### 测试辅助

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `test/keyboard-hook.py` | 跨平台全局键盘鼠标钩子监控器。打印按键/鼠标/滚轮事件并追踪前台窗口。同时可作为输入控制库使用：`press`、`release`、`tap`、`hotkey`、`send`（序列发送）、`move`、`click`、`scroll`、`get_foreground_window`。macOS 使用原生 CGEvent tap；Windows 用 ctypes 调用 `SetWindowsHookEx`；Linux 使用 X11 XRecord | 跨平台。macOS: `pip install pyobjc-framework-Quartz`；Windows: 无（标准库 ctypes）；Linux: `pip install python-xlib` |
| `test/print-argv.py`<br>`test/print-argv.sh`<br>`test/print-argv.ps1` | 打印所有命令行参数，分别对应 Python / Bash / PowerShell 实现，功能一致 | 跨平台。`.py` 需 `python3`；`.sh` 需 `bash`；`.ps1` 需 `PowerShell` |

---

## 依赖

核心工具模块：`utils/` — 提供 ANSI 颜色代码、光标/清屏控制序列和平台工具函数。

### Python 环境

**Windows / macOS / Linux：** 安装 [Miniconda](https://docs.conda.io/en/latest/miniconda.html)，然后在 base 环境中安装依赖：

```bash
conda run -n base python -m pip install -r requirements.txt
```

`requirements.txt` 包含 launcher 和普通工具的运行时依赖。Launcher 库使用兼容版本范围，普通工具库由 pip 选择当前可安装版本。

研究脚本通常仅由项目维护者使用。需要运行 `tools/research/` 下的脚本时，可连同基础依赖一起安装：

```bash
conda run -n base python -m pip install -r requirements-research.txt
```

如需安装独立程序打包器及平台专用可选 Python 集成：

```bash
conda run -n base python -m pip install -r requirements-optional.txt
```

启动器优先通过 `conda info --base` 定位 conda base 环境 Python，然后回退到已知安装路径和 `python3`。

### 外部工具

```bash
# Windows (scoop)
scoop install ffmpeg yt-dlp aria2 BBDown smartmontools ghostscript tailscale

# macOS (brew)
brew install ffmpeg yt-dlp aria2 smartmontools ghostscript tailscale ntfs-3g macfuse

# Linux (apt)
sudo apt install ffmpeg yt-dlp smartmontools ghostscript tailscale
```

---

## 约定

- 所有 Python 脚本支持 `--help` / `-h` 查看用法（英文，带颜色）
- 所有脚本统一使用 `Utils.print_banner()` 绘制双线框标题横幅
- 支持的运行时版本为 Python 3.13+
- 命令行参数传入时跳过交互提示（适合批处理）
- 多行输入使用 EOF（Windows: `Ctrl+Z`，Linux/macOS: `Ctrl+D`）
- 单行文本输入使用 `Input.prompt()`，支持默认值和 `transform` 回调（如 `str.upper`）
- `Menu.select()` 配合 `Menu.from_enum()` 提供交互式键盘枚举菜单，支持默认选项键
- 通过 `utils` ANSI 代码实现彩色输出（`FLYellow`、`FLGreen`、`FLRed` 等）
- 项目工具统一放在 `tools/`；平台相关脚本位于 `tools/windows/`、`tools/linux/`、`tools/macos/`
- 多路径输入提示支持通配符（``*``/``?``/``[abc]``）批量匹配文件；未匹配到文件的模式按原样字面路径处理
- 路径输入支持环境变量展开（Linux/macOS: ``$VAR``/``${VAR}``，Windows: ``%VAR%``）—— 仅展开已定义的变量，未定义的变量保留原文
