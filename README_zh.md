# Personal Scripts

[Click Here to read English version](./README.md)

**GitHub**: https://github.com/BH2WFR/PersonalScripts

**开源协议：GPL v3**

**私人使用跨平台日常实用脚本合集** — PDF 处理、文件链接、视频下载、系统工具等。

大部分脚本支持交互模式和命令行参数。使用 `python <脚本名>.py --help` 查看用法详情。



## 配置与启动指南

- **全平台：**

  - **conda 与 Python 环境：**

    - 本项目**默认使用 conda 中的 python**，并**使用 `base` 虚拟环境**；

    - 如本电脑无 conda，**建议安装体积占用极小的 miniconda**，而不是庞大臃肿的 anaconda；

    - 如需设置本项目启动时的 conda 虚拟环境名称（**不想用 `base` 环境**），请设置**环境变量 `ZL_CONDA_ENV`**，并输入目标虚拟环境名称。

    - Python 版本应为 **3.13+**

    - 需要安装的 python 库：

      - **大多数脚本（必装！）**：

        `PyYAML`, `pathspec`

      - 部分脚本依赖的特色库（**参考后面「脚本列表」章节**中所写的依赖库，下一行仅为举例，不代表实际依赖）：

        `mss`（截图）、`Pillow`/`matplotlib`/`numpy`/`opencv-python`（图像处理）、`ploltly`（图像可视化）、`pymupdf`/`pypdf`（pdf 处理）、`boto3`（S3 存储访问与上传）、`pynput`（键盘监听）

    - **一键依 python 库赖安装方法：**

      - 大部分依赖库用以下命令即可：
        ```sh
        conda run -n base python -m pip install -r requirements.txt
        ```

      - 需要运行 `tools/research/` 下的脚本时，用以下命令安装专有依赖库：

        ```sh
        conda run -n base python -m pip install -r requirements-research.txt
        ```

- **Windows：**

  - **仅支持 Windows 10 及以上版本的系统**；

  - 建议使用 **scoop 包管理器**安装命令行工具，并使用 **WinGet 包管理器**安装图形界面工具；

    > **强烈不建议**通过手动下载可执行文件，并通过添加环境变量的方式管理命令行工具，这非常烦琐。
    > 交给包管理器可大大减少在这方面耗费的时间，还能做到自动检测更新！

  - 建议**安装 powershell 7** （不是系统自带的 powershell 5）

  - 部分脚本需要**使用 `sudo` 命令原地提权**，应当用 scoop **安装 `gsudo` 这个工具**（[https://github.com/gerardog/gsudo](https://github.com/gerardog/gsudo)），否则部分脚本只能用管理员权限的命令行启动；

  - 如需 bash 支持，可**安装 git**，启动器启动时会从 `git` 命令所在路径，推出到 `git-bash` 的所在路径；

    - 后续可能会加入通过 cygwin 查找 bash 的功能，并让它优先于 通过 git 找 bash。

- **macOS：**

  - 建议使用 **homebrew 包管理器**安装命令行工具（Formulae）和图形界面工具（Cask）；
  - 部分工具（如 `macos/screen-utils`），仅支持 Apple Silicon 处理器的 mac 设备；

- **Linux：**

  - 如系统无图形界面，则部分涉及GUI、截屏等功能的工具无法启动。
  - Wayland 图形界面环境下，截图、键盘钩子等特殊功能会变得非常复杂，本项目并不保证这些功能在 linux 中的可用性。

- **其他：**

  - 推荐使用 UniGetUI 软件（[https://github.com/Devolutions/UniGetUI](https://github.com/Devolutions/UniGetUI)），图形化地管理系统包管理器，方便一键查找、安装、升级由包管理器安装的软件（windows 下的 scoop/winget，macos下的 brew 全部支持）
  - **建议将本路径加入到环境变量中**，方便直接通过 `run-script.ps1` 或 `run-script.sh` 启动启动器；

- **各脚本所依赖的 命令行工具 和 python 库：**

  - 参考后面「脚本列表」章节中的表格，并建议通过**包管理器**安装对应的依赖工具和 python 库。

    **参考安装命令（仅供参考，不可以直接复制粘贴运行）：**

    ```sh
    # Windows (scoop)
    scoop install ffmpeg yt-dlp aria2 BBDown smartmontools ghostscript tailscale
    
    # macOS (brew)
    brew install ffmpeg yt-dlp aria2 smartmontools ghostscript tailscale ntfs-3g macfuse
    
    # Linux (apt)
    sudo apt install ffmpeg yt-dlp smartmontools ghostscript tailscale
    ```



### 项目结构

核心工具包：`utils/` — 将控制台、运行环境、系统、路径及交互职责拆分为独立类，并由 `utils/__init__.py` 统一导出公共工具。

- **所有工具包**都在 **`./tools/` 目录**中，如 `./tools/network`, `./tools/research`, `./tools/windows` 等；

  - 但查找或执行脚本时，应忽略 `tools` 这一级；如脚本 `./tools/network/rclone-sync.py`，启动时应直接输入 `network/rclone-sync.py` 或 `rclone-sync`

- 所有 python 脚本**均依赖 `./utils` 中的共享轮子**，内含交互式文本输入/路径输入、交互式菜单选择、路径处理、提权、依赖工具检查、ANSI ESC 命令行文本颜色 等依赖功能。

  > **不可以把功能脚本单独拿出来运行**，会因找不到 `utils` 中的依赖代码而报错！

### 

### 如何使用启动器

```bash
# 交互模式：列出支持的脚本，按数字或名称选择
./run-script.sh                                # Linux/macOS
.\run-script.ps1                               # Windows

# 直接运行指定脚本（参数透传）
./run-script.sh <脚本名> [参数...]              # Linux/macOS
.\run-script.ps1 <脚本名> [参数...]             # Windows

# 仅列出可用脚本
./run-script.sh --list                         # Linux/macOS
.\run-script.ps1 --list                        # Windows
```

**启动器特性：**

- 无参数启动启动器时，会先检测系统/平台/架构，并检测 conda/python/pwsh/bash 环境可用性；检测完毕后，会**列出当前系统/平台/架构中支持的所有脚本**；列出所有脚本后通过键盘交互选择脚本并启动，支持参数透传：
  - 交互式选择支持**数字**或**脚本名称**（如 `15`、`macos/ntfs-3g-utils.py`、`ntfs-3g-utils`）
  - 将数字/名称后的参数**透传**给目标脚本（如 `15 --help`、`macos/screen-utils --list`、`screen-utils --list`）
  - 所有脚本**均支持省略父路径，直接输入脚本名**，如输入 `ntfs-3g-utils` 会自动递归查找此名称脚本，实际启动结果等价于输入 `macos/ntfs-3g-utils`。
    当不同目录中存在重名脚本时，会提示用户通过序号选择去重。
    - 注意：`tools` 这层应当忽略，启动器查找时是从 `./tools` 目录内部开始递归查找的
  - 所有脚本均支持省略扩展名，如 `macos/ntfs-3g-utils.py` 可直接输入 `ntfs-3g-utils` 或 `macos/ntfs-3g-utils`。
    如遇到同名但扩展名不同的脚本，启动器会提示用户通过序号选择去重。
  - **列出脚本时，可对指定平台/环境/架构隐藏部分脚本**：支持通过 `launcher-config.yaml` 设置各系统平台 （`windows`/`linux`/`macos`）、有无 GUI （`no-gui`，主要针对 linux 服务器）、处理器架构（`x86`, `x86_64`, `armv7`, `arm64`）来对指定平台/环境/架构的计算机隐藏部分脚本。
    - 解释器感知：无 `bash` 时隐藏 `.sh` 脚本；无 `pwsh` 时隐藏 `.ps1` 脚本
- 有参数启动启动器时，会根据参数自动查找脚本，并**透传剩余的参数**，此时不会打印出支持的脚本列表，直接启动目标脚本
  （如 `run-script.sh ntfs-3g-utils --list`，会自动找到  `macos/ntfs-3g-utils` 后执行，并透传 `--list` 参数到 `macos/ntfs-3g-utils` 中）
- 自动检测 Python：优先使用 `conda info --base` 查找 conda base 环境中的 python，再尝试已知路径，最后回退到 `python3`
  - 可通过设置**系统环境变量 `ZL_CONDA_ENV`** 来指定启动器执行脚本时，用的 **conda 虚拟环境名称**。默认为 `base`。
- **`ZL_SCRIPT_ADDITIONAL_PATH`** 用于发现附加目录，环境变量名本身也可配置。
  多个目录使用平台路径分隔符分隔（Windows 为 `;`，macOS/Linux 为 `:`）；相对路径以项目根目录为基准。每个目录显示为 `─── Additional [N] ───`（N 从 1 开始），并应用相同的配置化忽略规则。
  配合 **`@N:` 前缀** 可精确指定脚本来源：`@0:` = 主目录，`@1:` = 第一个附加目录（对应 `Additional [1]`），依此类推。裸名递归搜索所有分组；`@N:` 将相同匹配规则限制到指定分组。多个有效匹配会以带编号的 `@N:` 路径列出。CLI 同样可用（如 `python run-script.py @1:test.py`）
- 已预留脚本打包、依赖打包功能（`./deps` 目录中放置依赖的二进制可执行文件）功能，但目前未完整实现，也不打算优先实现。



### 其他特性

- 所有 Python 脚本支持通过附加 `--help` / `-h` 参数，以查看用法与帮助文档

- **交互输入相关：**

  - 多行输入使用 EOF 终止（Windows: `Ctrl+Z` `Enter` ，Linux/macOS: `Ctrl+D`）
  - **路径输入支持环境变量展开**（Linux/macOS: ``$VAR``/``${VAR}``，Windows: ``%VAR%``）
    （仅展开已定义的变量，未定义的变量保留原文）

  - 多路径输入提示支持通配符（``*``/``?``/``[abc]``）批量匹配文件；
    未匹配到文件的模式按原样字面路径处理

- 项目工具统一放在 `tools/`；平台相关脚本位于 `tools/windows/`、`tools/linux/`、`tools/macos/`



---

## 脚本列表

### PDF 工具

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/document-processing/pdf-compress.py` | 基于 ghostscript 的 **PDF 压缩器**：<br />支持 Ebook（标准）和 Custom（自定义 DPI/质量）模式 | `ghostscript` |
| `tools/document-processing/pdf-decrypt.py` | **PDF 解密工具**：<br />可解密可以打开阅读，但编辑权限被保护加密的 PDF 文件。 | **Python 库**：`pypdf` |
| `tools/document-processing/pdf-bookmarks-add.py` | **扫描版 PDF 书籍目录注入工具**：<br />先手动将目录页截图发给**多模态 LLM（如 Qwen3-VL）生成指定格式的  JSON**（含页码/层级/编号/标题），本脚本可以用输入的 JSON 准确地将对应的目录打入目标 PDF 文件中。 | **Python 库**：`pypdf` |
| `tools/document-processing/document-screenshot.py` | **针对加密文档的自动截图抓取工具**：<br />基于模拟 PgDn 翻页 + 鼠标点击自动翻页，并通过自动截图来获取内容，适用于**全自动抓取并保存被 DRM 保护、或加密 USB 中的 PDF** 文件内容<br /><br />建议使用高分辨率屏幕，并将屏幕方向改为纵向，然后调整文档页面的显示范围（不超出屏幕范围、并能充分利用屏幕空间）后，再用本脚本自动截图抓取。<br />macos 中，还需要额外设置对应的屏幕录制权限才可以正常运行。 | 仅 **Windows/macOS**<br />**Python 库**：`mss`、`pynput`、`Pillow` |



### 视频下载

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/download/download-bilibili.py` | **基于 BBDown 的 B 站视频下载器**：<br />（画质/仅音频/字幕/弹幕/多 API） | `BBDown`、`ffmpeg`、`aria2`（可选） |
| `tools/download/download-yt.py`       | **基于 yt-dlp 的 视频下载工具**：<br />（画质/音频/字幕/cookies/播放列表） | `yt-dlp`、`ffmpeg`、`deno`（可选） |
| `tools/download/download-m3u8.py` | **基于 yt-dlp 的 m3u8/HLS 流媒体下载器**                     | `yt-dlp`、`ffmpeg`                  |

### 视频/图片编辑

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/multimedia/ffmpeg-crop-video.py` | **基于 ffmpeg 的视频裁剪工具**：<br />注意非画面裁剪，是**按时间裁剪** | `ffmpeg`                                |
| `tools/research/batch-crop-images.py` | **基于 opencv 的批量图片裁剪工具**：<br />按画面 ROI 区域裁剪 | **Python 库**：`opencv-python`、`numpy` |

### 文件系统/磁盘挂载

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/filesystem/openssl-file-hash.py` | 基于 OpenSSL 的**文件哈希值计算工具**：<br />可递归或批量，支持 `md5` `sha256` 等各种 openssl 支持的常见算法。 | `openssl` |
| `tools/filesystem/check-filename-overlong.py` | **长文件名自动截断工具**：<br />按 UTF-8 编码统计字节长度，自动截断超过指定字节数（默认 143，适配群晖的加密文件夹限制）的文件名。<br />截断时保留扩展名，若发生重名则在扩展名前自动加 `_1`、`_2` 等后缀 |  |
| `tools/filesystem/modify-file-time.py`        | **文件/文件夹时间戳修改工具**（创建/修改/访问时间），支持加入随机抖动，支持备份/还原指定文件夹下所有文件/文件夹的时间 |  |
| `tools/macos/ntfs-3g-utils.py`                | 仅 macOS，**基于 ntfs-3g-mac 的 NTFS 分区可写挂载工具**：<br />支持自动扫描检测 NTFS 分区，支持卸载/弹出分区 | **仅 macOS**<br />需在安全模式下允许来自认可开发者的内核扩展，并安装内核扩展 `macFUSE` 和挂载工具 ` ntfs-3g-mac` |

### 文件系统/符号链接工具

| 脚本                                               | 描述                                                         | 依赖           |
| -------------------------------------------------- | ------------------------------------------------------------ | -------------- |
| `tools/filesystem/link-create.py`                  | **符号链接/硬链接创建工具**（Windows 下还支持生成 目录软链接 SYMLINMKD 和 JUNCTION）：<br />支持相对路径、镜像模式、冲突处理 |                |
| `tools/filesystem/link-scan.py`                    | **递归在目录中检测并打印所有符号链接、硬链接的工具**（windows 下还会打印 目录软链接 SYMLINKD 和 JUNCTION）：<br />可自动检测死链（目标不存在），并提供自动修复或删除功能；Windows 下可将错误指向目录的文件软链接修复回 SYMLINKD。 |                |
| `tools/filesystem/link-fix-to-symlinkd-windows.py` | Windows 专用：将指向目录的文件软链接（SYMLINK）**修复**为正确的**目录软链接**（SYMLINKD）：<br />用于修复某些文件同步工具错误地按照 linux 上的方法，不区分文件软链接和目录软链接，将目录软链接错误地弄成文件软链接，导致无法访问的问题。 | 仅 **Windows** |

### 文件系统/权限工具

| 脚本                                    | 描述                                                         | 依赖                     |
| --------------------------------------- | ------------------------------------------------------------ | ------------------------ |
| `tools/filesystem/batch-add-chmod-x.sh` | **Linux/macOS 下，批量给脚本文件添加可执行权限的工具**：<br />递归查找指定扩展名（默认 `.py`/`.sh`）的文件，并用添 `chmod +x` 添加可执行权限，需要 sudo 提权 | **Linux/macOS**          |
| `tools/git-batch-add-chmod-x.ps1`       | **Windows 下，给 git 仓库中的脚本文件批量添加可执行权限的工具**：<br />将 git 暂存区中 `.py`/`.sh` 文件通过 `git update-index --chmod=+x` 标记为可执行，方便跨平台开发时 Windows 端提交的文件在 Linux/macOS 上 clone 后自带 `+x` 权限 | **Windows**<br />``git`` |
| `tools/macos/remove-quarantine.py`      | 仅 macOS，**文件 quarantine 和 provenance 属性批量移除工具**（基于 `xattr` 命令） | **仅 macOS**             |



### 网络工具

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/network/tailscale-restart-accept-routes.py` | **Tailscae Subnet Route 功能 快捷重启工具**：<br />通过切换 `--accept-routes` 开关重启 Tailscale 子网路由；<br />适用于 macos 中解决 tailscale 开启 subnet route 后，回家再离家后该功能被自动关闭的问题 | `tailscale` |
| `tools/network/rclone-sync.py` | **基于 YAML 配置的 rclone 同步任务手动运行器**：<br />支持可复用 profile、按机器过滤 sub-task、适用于 sync/copy/move 的方向选择、适用于 sync/copy/move/bisync 的比较模式选择（`size_and_time`、`size_only`、`force`、`checksum`）、备选远端、修改时间检查、dry-run、pre-check，以及在 rclone 操作期间用 Ctrl+C 取消（交互模式返回任务菜单；使用 `--task` 时退出码 130） | `rclone`<br />**Python 库**：`PyYAML` |
| `tools/network/upload-ipaddress.py` | **本机网卡信息收集上传工具：**<br />收集本机网卡信息，由其是本机 ip 地址，（基于 `ipconfig`/`ip addr`）并上传至 S3 存储卷，方便远程访问。<br />凭据来自环境变量：`ZL-IP-ADDRESS-S3-BUCKET`、`ZL-IP-ADDRESS-S3-ENDPOINT`、`ZL-IP-ADDRESS-S3-ID`、`ZL-IP-ADDRESS-S3-SECRET` | **Python 库：**`boto3` |
|                                                    |                                                              |                                       |
| `tools/windows/firewall-app-blocker.py` | 仅 Windows，**给 exe 文件，基于系统防火墙断网的工具：**<br />支持**递归查找某路径下所有 exe 文件**，支持增加断网规则、去除断网规则（恢复原状）。<br />本脚本需要**提权**到管理员权限。 | **仅 Windows**<br />`gsudo` |
| `tools/network/webserver-run.py` | **将本地文件夹（或含 `index.html` 的网页目录）映射为本地 HTTP 服务的工**具：<br />使用基于 Python 内置 `http.server` 的多线程服务，支持交互模式（目录/绑定地址/端口）或 CLI（`--dir`、`--bind`、`--port`） |                                       |

### 打开方式

| 脚本                                | 描述                                                         | 依赖                                    |
| ----------------------------------- | ------------------------------------------------------------ | --------------------------------------- |
| `tools/windows/file-association.py` | 仅 Windows，**给指定扩展名的文件**，在系统中**注册用指定 exe 作为打开方式**的工具<br />可用于给一些便携软件，注册对指定扩展名的打开方式 | **仅 Windows**<br />Python 库：`winreg` |
| `tools/macos/script-to-app.py`      | 仅 macOS，**将任意 python 脚本打包为 macOS `.app` 包的工具**：<br /> 用于**将任意 Python 脚本 作为文件的打开方式** | **仅 macOS**                            |

### 文本处理

| 脚本                            | 描述                                                         | 依赖                                 |
| ------------------------------- | ------------------------------------------------------------ | ------------------------------------ |
| `tools/parse-unicode-string.py` | **Unicode 字符信息显示工具**：<br />可获取输入文本中每个字符的 序号、字符、十六进制、十进制、说明 等信息，特殊字符（如控制符或空格等）有特殊标注格式。<br />支持用 `--clip`（剪贴板读取）参数来从剪贴板读取文本，也可以用正常的多行交互输入。 | Linux 剪贴板需 `wl-paste` 或 `xclip` |

### 显示器工具

| 脚本                                      | 描述                                                         | 依赖                                                         |
| ----------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| `tools/windows/show-screen-resolution.py` | 仅 Windows，**屏幕分辨率/缩放率查看工具**：<br />用于 RDP 连接中，解决设置界面中看不到当前远程电脑的屏幕分辨率和缩放率的问题； | **仅 Windows**                                               |
| **`tools/macos/screen-utils.py`**         | 仅 macOS Apple Silicon，显示器管理工具 — 旋转、分辨率、亮度（内建 + 外接显示器 DDC/CI）、色彩模式诊断、外接显示器强制 RGB 输出覆写。<br />**特色功能**：**MacBook 连接外接显示器时，可一键开关笔记本自带屏幕**（`--toggle-built-in`。**支持旋转显示器方向、修改外接显示器亮度**。 | **仅 macOS**（Apple Silicon）<br />**可选 Python 库**： `pyobjc-framework-Cocoa` |

### 隐私与清理

| 脚本                                          | 描述                                                         | 依赖                                        |
| --------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------- |
| `tools/windows/clear-recycle-bin.py`          | 仅 Windows，**回收站强力清空工具**：<br />用于解决**回收站中存在 0 kb 文件/文件夹，但是无法清空**（清空后这些件仍然存在于回收站中）的问题。<br />遇到符号链接，仅删除链接本身，不会遍历指向的目标。 | **仅 Windows**                              |
| `tools/windows/clear-all-event-logs.py`       | 仅 Windows，**系统日志一键清空工具**                         | **仅 Windows**                              |
| `tools/windows/clear-privacy.py`              | 仅 Windows，**隐私痕迹清除工具**：<br />（资源管理器历史、事件日志、DNS 缓存、浏览器数据、凭据、临时文件等），支持逐项确认。<br />**免责声明：使用风险自负。** 本脚本允许时需要**提权**。 | **仅 Windows**<br />`gsudo`                 |
| `tools/macos/clear-privacy.py`                | 仅 macOS，**隐私痕迹清除工具**：<br />（最近项目、访达状态、Shell 历史、浏览器数据、缓存、日志等），支持逐项确认。<br />**免责声明：使用风险自负。** | **仅 macOS**<br />可选 `brew install trash` |
| `tools/filesystem/remove-os-junk-files.py`    | **系统生成垃圾文件递归删除工具**：<br />（`.DS_Store`、`__MACOSX__`、`Thumbs.db` 等） |                                             |
| `tools/windows/clear-android-rndis-record.py` | 仅 Windows，**清理注册表中残留的 Android USB 网络共享/RNDIS 记录的工具**：<br />用于解决 Android 设备连接到电脑后，每次打开 USB 网络共享时，电脑中的**网络连接编号不断递增**的问题 | **仅 Windows**                              |

### 系统工具

| 脚本                                       | 描述                                                         | 依赖                                             |
| ------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------ |
| `tools/windows/restart-windows-service.py` | 仅 Windows，**系统服务强制重启工具**：<br />内置 Windows Audio 预设，**可用于临时修复 RDP 远程桌面会话中，无法重定向被控方电脑声音的问题** | **仅 Windows**<br />`gsudo`                      |
| `tools/power-current.py`                   | 充电器与电池遥测查看器，**可在 macOS 中查看当前电脑的充电功率**。<br />macOS 使用 `ioreg`，Windows 使用 PowerShell CIM/WMI，Linux 使用 `/sys/class/power_supply`。部分字段可能因固件/驱动限制不可用。（**本脚本仅在 macOS 中有最佳体验**） | **macOS 中体验最佳**，也支持其他系统（数据不全） |
| `tools/disk-smart-info.py`                 | 基于 smartmontool 的**磁盘健康信息查看器**：<br />列出 SMART 磁盘并显示详细属性（写入量、通电时间、剩余寿命等） | `smartmontools`                                  |

### 科研工具

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/research/npy-viewer.py` | **`.npy`/`.npz` 文件交互式查看器**：<br />1D 折线/柱状/散点图，2D 热力图/曲面图 | **Python 库**：`numpy`、`matplotlib`、`plotly` |
| **`tools/research/pattern-generator.py`** | **结构光投影图案生成器**：<br />非专业人员请勿使用 | Python 库：`opencv-python`、`numpy` |

### 测试/辅助脚本

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/keyboard-hook-viewer.py` | **全局键盘鼠标钩子监控器**：<br />macOS 使用 CGEvent tap 与 IOHID（可显示事件来源设备 ID）；Windows 用 ctypes 调用 `SetWindowsHookEx`；Linux 使用 X11 XRecord | **不支持 Linux Wayland**<br />macOS: `pip install pyobjc-framework-Quartz`；Windows: 无（标准库 ctypes）；Linux: `pip install python-xlib` |
| `test/print-argv.py`<br>`test/print-argv.sh`<br>`test/print-argv.ps1` | **命令行参数打印工具**：<br />可打印出所有传到 脚本的 argv 参数，用于判断 脚本传入参数是否正确 |  |



