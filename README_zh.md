# Personal Scripts

[English](./README.md)

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

# 将 run-script.py 编译为独立可执行文件（需要 Nuitka）
python _nuitka-build.py                        # 全平台
```

**启动器特性：**

- 交互式选择支持**数字**或**脚本名称**（如 `15`、`macos/ntfs-3g-utils`）
- 数字/名称后的参数**透传**给目标脚本（如 `15 --help`、`macos/screen-utils --list`）
- 平台感知过滤：隐藏与当前 OS 不匹配的 `windows/`/`macos/`/`linux/` 脚本
- 解释器感知：无 `bash` 时隐藏 `.sh` 脚本；无 `pwsh` 时隐藏 `.ps1` 脚本
- 同路径存在同名 `.py` 和 `.sh`/`.ps1` 时，仅显示 `.py`
- 自动检测 Python：优先使用 miniconda/anaconda，回退到 `python3`
- `_nuitka-build.py` 可将 `run-script.py` 编译为单个独立可执行文件（内嵌 Python 运行时，需安装 Nuitka）

---

## 脚本列表

### PDF 工具

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `pdf-compress.py` | PDF 压缩工具，支持 Ebook（标准）和 Custom（自定义 DPI/质量）模式 | 跨平台。`ghostscript` |
| `pdf-decrypt.py` | 解密受密码保护的 PDF（含仅权限保护），保留完整文档结构 | 跨平台。`pip install pypdf` |
| `pdf-bookmarks-add.py` | 通过 LLM 生成的 JSON（页/层级/编号/标题）为 PDF 添加目录书签 | 跨平台。`pip install pypdf` |
| `document-screenshot.py` | 自动截图 PDF 文档（模拟 PgDn 翻页 + 鼠标点击） | 仅 macOS。`pip install mss pynput Pillow` |

### 视频下载

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `download-bilibili.py` | B 站视频下载器（画质/仅音频/字幕/弹幕/多 API） | 跨平台。`BBDown`、`ffmpeg`、`aria2`（可选） |
| `download-yt.py` | YouTube 视频下载器（画质/音频/字幕/cookies/播放列表） | 跨平台。`yt-dlp`、`ffmpeg`、`deno`（可选） |
| `download-m3u8.py` | m3u8/HLS 流媒体下载器，支持自定义请求头 | 跨平台。`yt-dlp`、`ffmpeg` |

### 视频/图片编辑

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `ffmpeg-crop-video.py` | 按时间段裁切视频（非画面裁剪） | 跨平台。`ffmpeg` |
| `research/batch-crop-images.py` | 批量裁剪图片，交互式选择 ROI 区域 | 跨平台。`pip install opencv-python numpy` |

### 文件系统与链接

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `link-create.py` | 跨平台符号链接/硬链接创建（Windows: SymlinkD, Junction；Linux/macOS: Symlink, Hardlink）。支持相对路径、镜像模式、冲突处理 | 跨平台。无外部依赖 |
| `link-scan.py` | 递归扫描目录中的符号链接、Junction、硬链接。检测死链，自动修复或删除 | 跨平台。无外部依赖 |
| `windows/link-fix-symlinkd.py` | Windows 专用：将损坏的目录符号链接转换为 SymlinkD | 仅 Windows。无外部依赖 |
| `check-filename-overlong.py` | 检查并截断超出 UTF-8 字节限制的超长文件名（如群晖 NAS 143 字节限制） | 跨平台。无外部依赖 |
| `remove-os-junk-files.py` | 递归删除系统生成的垃圾文件（`.DS_Store`、`__MACOSX__`、`Thumbs.db` 等） | 跨平台。无外部依赖 |
| `modify-file-time.py` | 修改文件/文件夹时间戳（创建/修改/访问时间），支持随机抖动 | 跨平台。无外部依赖 |
| `batch-add-chmod-x.sh` | 通过 git 递归为 `.py`/`.sh` 文件添加 `chmod +x`（需 sudo） | Linux/macOS。`git`、`sudo`（系统自带） |
| `git-batch-add-chmod-x.ps1` | PowerShell 版：在 git 索引中标记 `.py`/`.sh` 文件为可执行 | Windows。`PowerShell`、`git` |

### 系统与网络

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `disk-smart-info.py` | 跨平台 SMART 磁盘健康信息查看器，列出 SMART 磁盘并显示详细属性 | 跨平台。`smartmontools` |
| `tailscale-restart-accept-routes.py` | 通过切换 `--accept-routes` 开关重启 Tailscale 子网路由 | 跨平台。`tailscale` |
| `upload-ipaddress.py` | 收集网络信息并上传至腾讯云 COS S3 方便远程访问。凭据来自环境变量 | 跨平台。`pip install boto3` |
| `macos/ntfs-3g-utils.py` | macOS 专用：通过 ntfs-3g（macFUSE）挂载 NTFS 磁盘，支持读写。挂载/系统挂载/弹出 | 仅 macOS。`brew install ntfs-3g macfuse` |
| `macos/screen-utils.py` | macOS 专用（Apple Silicon）：显示器管理 — 旋转、亮度（内建 + DDC/CI）、切换内建显示器。CLI：`--list`、`--toggle`、`--ddc-ci-info`、`--help` | 仅 macOS（Apple Silicon）。无外部依赖；可选 `pip install pyobjc` |
| `power-current.py` | 跨平台充电器与电池遥测查看器。macOS 使用 `ioreg`，Windows 使用 PowerShell CIM/WMI，Linux 使用 `/sys/class/power_supply`。部分字段可能因固件/驱动限制不可用。 | 跨平台。无外部依赖 |
| `macos/remove-quarantine.py` | macOS 专用：移除文件/文件夹的 quarantine 隔离属性（支持递归批量，可选清 provenance，逐文件计数） | 仅 macOS。使用 `xattr`（系统自带） |
| `windows/clear-android-rndis-record.ps1` | 清理 Windows 注册表中残留的 Android USB 网络共享/RNDIS 配置 | 仅 Windows。PowerShell（系统自带） |
| `windows/clear-privacy.py` | 清除 Windows 隐私痕迹（资源管理器历史、事件日志、DNS 缓存、浏览器数据、凭据、临时文件等），支持逐项确认。**免责声明：使用风险自负。** | 仅 Windows。系统自带工具；可选 `scoop install sudo gsudo` |
| `windows/show-screen-resolution.ps1` | 通过 Windows API 显示显示器分辨率和屏幕信息 | 仅 Windows。PowerShell（系统自带） |
| `macos/clear-privacy.py` | 清除 macOS 隐私痕迹（最近项目、访达状态、Shell 历史、浏览器数据、缓存、日志等），支持逐项确认。**免责声明：使用风险自负。** | 仅 macOS。系统自带工具；可选 `brew install trash` |
| `webserver-run.py` | 运行本地 HTTP 服务器以提供静态网页工具。支持交互模式（目录/绑定地址/端口）或 CLI（`--dir`、`--bind`、`--port`）。使用 Python 内置 `http.server`，支持多线程 | 跨平台。无外部依赖 |
| `webserver-run.bat` | Windows：webserver-run 的双击启动器 | Windows。无外部依赖 |

### 实用工具

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `parse-unicode-string.py` | 解析并显示 Unicode 字符信息（序号、字符、十六进制、十进制、说明），特殊字符彩色标注。支持 `--clip`（剪贴板读取）、`--pause`（回车后退出）、`--help` | 跨平台。无外部依赖；Linux 剪贴板需 `wl-paste` 或 `xclip` |
| `research/npy-viewer.py` | `.npy`/`.npz` 文件交互式查看器（1D 折线/柱状/散点图，2D 热力图/曲面图） | 跨平台。`pip install numpy matplotlib plotly` |
| `research/npy-viewer.bat` | Windows：npy 查看器的双击/拖拽启动器 | Windows。需 `npy-viewer.py` 依赖 |
| `research/npy-viewer.sh` | Linux/macOS：npy 查看器的双击启动器 | Linux/macOS。需 `npy-viewer.py` 依赖 |
| `run-script.py` | Python 启动器，可运行仓库内任意脚本 | 跨平台。`python3` |
| `run-script.sh` | Bash 启动器，可运行仓库内任意脚本 | Linux/macOS。`bash`、`python3` |
| `run-script.ps1` | PowerShell 启动器，可运行仓库内任意脚本 | Windows。`PowerShell`、`python` |
| `_nuitka-build.py` | 编译脚本：将 `run-script.py` 编译为独立可执行文件 | 跨平台。`pip install nuitka` |
| `macos/script-to-app.py` | 创建 macOS `.app` 包，将任意 Python 脚本包装为可双击启动的应用程序，用于通过访达"打开方式"关联文件类型 | 仅 macOS。无外部依赖 |
| `windows/script-to-app.py` | 创建 Windows `.cmd` 启动器，将任意 Python 脚本安装到 `Program Files`。自动检测 Python（conda/系统），接收打开的文件路径作为参数，支持"打开方式"关联文件类型 | 仅 Windows。无外部依赖 |

### 测试辅助

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `test/keyboard-hook.py` | 跨平台全局键盘鼠标钩子监控器。打印按键/鼠标/滚轮事件并追踪前台窗口。同时可作为输入控制库使用：`press`、`release`、`tap`、`hotkey`、`send`（序列发送）、`move`、`click`、`scroll`、`get_foreground_window`。macOS 使用原生 CGEvent tap；Windows 用 ctypes 调用 `SetWindowsHookEx`；Linux 使用 X11 XRecord。 | 跨平台。macOS: `pip install pyobjc-framework-Quartz`。Windows: 无（标准库 ctypes）。Linux: `pip install python-xlib`。 |
| `test/print-argv.py` | 打印所有命令行参数 | 跨平台。无外部依赖 |
| `test/print-argv.ps1` | PowerShell：彩色打印所有参数 | Windows。PowerShell（系统自带） |
| `test/print-argv.sh` | Bash：彩色打印所有参数 | Linux/macOS。`bash`（系统自带） |
| `test/keyboard-hook.py` | 全局键盘鼠标钩子监视器（按下/释放/点击/滚轮）。也可发送输入（按下、轻击、组合键、移动、点击、滚轮）。通过 `setup()` API 支持热键回调 | macOS（pyobjc）、Windows（标准库 ctypes）、Linux（python-xlib/X11） |

---

## 依赖

核心工具模块：`utils/` — 提供 ANSI 颜色代码、光标/清屏控制序列和平台工具函数。

### Python 环境

**Windows / macOS / Linux：** 安装 [Miniconda](https://docs.conda.io/en/latest/miniconda.html)，然后在 base 环境中安装依赖：

```bash
pip install pypdf boto3 opencv-python mss pynput Pillow matplotlib numpy plotly
```

启动器自动检测 `~/miniconda3/bin/python`。

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
- 命令行参数传入时跳过交互提示（适合批处理）
- 多行输入使用 EOF（Windows: `Ctrl+Z`，Linux/macOS: `Ctrl+D`）
- 通过 `utils` ANSI 代码实现彩色输出（`FLYellow`、`FLGreen`、`FLRed` 等）
- 平台相关脚本放在 `windows/`、`linux/`、`macos/` 子目录中
