# Personal Scripts

[English](./README.md)

跨平台日常实用脚本合集 — PDF 处理、文件链接、视频下载、系统工具等。

大部分脚本支持交互模式和命令行参数。使用 `python <脚本名>.py --help` 查看用法详情。

## 快速开始

```bash
# 交互模式：列出支持的脚本，按数字选择
./run-script.sh                                # Linux/macOS
.\run-script.ps1                               # Windows

# 直接运行指定脚本
./run-script.sh <脚本名> [参数...]              # Linux/macOS
.\run-script.ps1 <脚本名> [参数...]             # Windows

# 仅列出可用脚本
./run-script.sh --list                         # Linux/macOS
.\run-script.ps1 --list                        # Windows
```

**启动器特性：**
- 按数字交互式选择脚本（根目录脚本优先，子目录次之）
- 平台感知过滤：Linux/macOS 启动器隐藏 `windows/` 脚本，Windows 启动器隐藏 `linux/` 和 `macos/` 脚本；Linux 额外隐藏 `macos/`，macOS 额外隐藏 `linux/`
- 自动检测 Python：优先使用 miniconda/anaconda，回退到 `python3`
- Linux 无 conda 时自动创建 `.venv` 以绕过 PEP 668 限制
- 同路径存在同名 `.py` 和 `.sh`/`.ps1` 时，仅显示 `.py`

---

## 脚本列表

### PDF 工具

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `pdf-decrypt.py` | 解密受密码保护的 PDF（含仅权限保护），保留完整文档结构 | `pypdf` |
| `pdf-bookmarks-add.py` | 通过 LLM 生成的 JSON（页/层级/编号/标题）为 PDF 添加目录书签 | `pypdf` |
| `document-screenshot.py` | 自动截图 PDF 文档（模拟 PgDn 翻页 + 鼠标点击） | `mss`, `pynput`, `Pillow` |

### 视频下载

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `download-bilibili.py` | B 站视频下载器（画质/仅音频/字幕/弹幕/多 API） | `BBDown`, `ffmpeg`, `aria2`（可选） |
| `download-yt.py` | YouTube 视频下载器（画质/音频/字幕/cookies/播放列表） | `yt-dlp`, `ffmpeg` |
| `download-m3u8.py` | m3u8/HLS 流媒体下载器，支持自定义请求头 | `yt-dlp`, `ffmpeg` |

### 视频/图片编辑

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `ffmpeg-crop-video.py` | 按时间段裁切视频（非画面裁剪） | `ffmpeg` |
| `research/batch-crop-images.py` | 批量裁剪图片，交互式选择 ROI 区域 | `cv2` |

### 文件系统与链接

| 脚本 | 描述 |
|------|------|
| `link-create.py` | 跨平台符号链接/硬链接创建（Windows: SymlinkD, Junction；Linux/macOS: Symlink, Hardlink）。支持相对路径、镜像模式、冲突处理 |
| `link-scan.py` | 递归扫描目录中的符号链接、Junction、硬链接。检测死链，自动修复或删除 |
| `link-fix-symlinkd.py` | Windows 专用：将损坏的目录符号链接转换为 SymlinkD |
| `check-filename-overlong.py` | 检查并截断超出 UTF-8 字节限制的超长文件名（如群晖 NAS 143 字节限制） |
| `remove-os-junk-files.py` | 递归删除系统生成的垃圾文件（`.DS_Store`、`__MACOSX__`、`Thumbs.db` 等） |
| `modify-file-time.py` | 修改文件/文件夹时间戳（创建/修改/访问时间），支持随机抖动 |
| `batch-add-chmod-x.sh` | 通过 git 递归为 `.py`/`.sh` 文件添加 `chmod +x`（需 sudo） |
| `git-batch-add-chmod-x.ps1` | PowerShell 版：在 git 索引中标记 `.py`/`.sh` 文件为可执行 |

### 系统与网络

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `disk-smart-info.py` | 跨平台 SMART 磁盘健康信息查看器，列出 SMART 磁盘并显示详细属性 | `smartmontools` |
| `tailscale-restart-accept-routes.py` | 通过切换 `--accept-routes` 开关重启 Tailscale 子网路由 | `tailscale` |
| `upload-ipaddress.py` | 收集网络信息并上传至腾讯云 COS S3 方便远程访问。凭据来自环境变量 | `boto3` |
| `macos/ntfs-3g-utils.py` | macOS 专用：通过 ntfs-3g（macFUSE）挂载 NTFS 磁盘，支持读写。挂载/系统挂载/弹出 | `ntfs-3g` |
| `macos/screen-utils.py` | macOS 专用（Apple Silicon）：显示器管理 — 旋转、亮度（内建 + DDC/CI）、切换内建显示器 | — |
| `macos/remove-quarantine.py` | macOS 专用：移除文件/文件夹的 quarantine 隔离属性（支持批量） | — |
| `windows/clear-android-rndis-record.ps1` | 清理 Windows 注册表中残留的 Android USB 网络共享/RNDIS 配置 | — |
| `windows/show-screen-resolution.ps1` | 通过 Windows API 显示显示器分辨率和屏幕信息 | — |

### 实用工具

| 脚本 | 描述 |
|------|------|
| `parse-unicode-string.py` | 解析并显示 Unicode 字符信息（序号、字符、十六进制、十进制、说明），特殊字符彩色标注 |
| `research/npy-viewer.py` | `.npy`/`.npz` 文件交互式查看器（1D 折线/柱状/散点图，2D 热力图/曲面图） |
| `research/npy-viewer.bat` | Windows：npy 查看器的双击/拖拽启动器 |
| `research/npy-viewer.sh` | Linux/macOS：npy 查看器的双击启动器 |
| `run-script.sh` | Bash 启动器，可运行仓库内任意脚本 |
| `run-script.ps1` | PowerShell 启动器，可运行仓库内任意脚本 |

### 测试辅助

| 脚本 | 描述 |
|------|------|
| `test/print-argv.py` | 打印所有命令行参数 |
| `test/print-argv.ps1` | PowerShell：彩色打印所有参数 |
| `test/print-argv.sh` | Bash：彩色打印所有参数 |

---

## 依赖

核心工具模块：`my_utils/` — 提供 ANSI 颜色代码、日志助手和平台工具函数。

### Python 环境

**Windows / macOS / Linux：** 安装 [Miniconda](https://docs.conda.io/en/latest/miniconda.html)，然后在 base 环境中安装依赖：

```bash
pip install pypdf boto3 opencv-python mss pynput Pillow matplotlib numpy
```

启动器自动检测 `~/miniconda3/bin/python`。

外部工具（通过包管理器安装）：
```bash
scoop install ffmpeg yt-dlp aria2 BBDown    # Windows
brew install ffmpeg yt-dlp aria2             # macOS
apt install ffmpeg yt-dlp                    # Linux
```

---

## 约定

- 所有 Python 脚本支持 `--help` / `-h` 查看用法（英文，带颜色）
- 命令行参数传入时跳过交互提示（适合批处理）
- 多行输入使用 EOF（Windows: `Ctrl+Z`，Linux/macOS: `Ctrl+D`）
- 通过 `my_utils` ANSI 代码实现彩色输出（`FLYellow`、`FLGreen`、`FLRed` 等）
- 平台相关脚本放在 `windows/`、`linux/`、`macos/` 子目录中
