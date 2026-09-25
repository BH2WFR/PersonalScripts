# Personal Scripts

[Click Here to read English version](./README.md)

**GitHub**: https://github.com/BH2WFR/PersonalScripts

**开源协议：GPL v3**

**个人使用的跨平台日常实用脚本合集**——涵盖 PDF 处理、文件链接、视频下载和系统工具等。

**主要特色功能如下**：（完整内容请查看后面的[「脚本列表」](#脚本列表)章节，加粗的为其中的重点功能）

> - **研究相关**
>   - `.npy`/`.npz` 文件交互式查看器，支持折线图、热力图和三维曲面等可视化方式
>   - 图片批量裁剪工具
> - **Windows 相关**
>   - **Windows 事件日志一键清除工具**
>   - **Android USB 网络共享记录清除工具**，解决每次开启 USB 网络共享时本地连接序号持续递增的问题
>   - 强制重启 `Windows Audio` 或其他系统服务，可用于临时修复 RDP 会话中声音无法重定向的问题
>   - 强制**清空回收站**，解决部分 OneDrive 文件删除后在回收站中留下无法清除的 0 KB 项目的问题
>   - 将**指定目录下**的所有  `.exe`/`.com` 文件，**批量加入防火墙禁止联网规则**的工具
>   - 为指定扩展名注册应用程序打开方式的工具集
>   - 将任意 Python 脚本包装为可用于文件打开方式的 CMD 启动器
> - **macOS 相关**
>   - 基于 ntfs-3g-mac 的 **NTFS 可写挂载工具**
>   - 显示器工具：**MacBook 连接外接显示器时可关闭自带屏幕**，也可旋转屏幕方向、调整外接显示器亮度
>   - 将任意 Python 脚本包装为可用于文件打开方式的 `.app`
> - **文件系统**
>   - **符号链接工具**：创建符号链接或硬链接，并递归查看目录中的链接
>   - 在 Windows 下将错误指向目录的文件软链接，修复为目录软链接（SYMLINKD）的工具
>   - **批量修改文件时间工具**，支持备份、还原时间功能，支持修改时间时给不同文件加入随机抖动
>   - **批量截断过长文件名**，并保留扩展名
>   - **批量计算文件哈希值**
>   - `Thumbs.db` `.DS_Store` 等文件递归清除工具
> - **文档工具**
>   - PDF 解密和编辑限制解除工具
>   - **PDF 目录（书签）注入工具**——使用视觉LLM读取书籍目录，并将结果输入到脚本中，给 PDF 打入目录
>   - PDF 压缩工具（调用 ghostscript）
>   - **文档自动截屏工具**——通过自动翻页和截图，扒取禁止下载或位于加密存储设备中的文档
> - **网络工具**
>   - 带同步 profile 读取功能的 **rclone 交互式手动同步工具**
>   - 将本地带 `index.html` 的网页项目**部署为网页服务**的工具
> - **视频工具**
>   - 基于 BBDown 的 B 站视频下载工具
>   - 基于 yt-dlp 的网页视频下载工具（包括 m3u8）
>   - 基于 ffmpeg 的视频时间裁剪工具
> - Unicode 字符解析查看工具
> - 全局键盘鼠标钩子测试器

大部分脚本支持交互模式和命令行参数。使用 `python <脚本名>.py --help` 查看用法详情。



## 配置与启动指南

- **Conda 与 Python 环境：**

  - 本项目**默认使用 Conda 中的 Python**，并**使用 `base` 虚拟环境**；

  - 如本电脑无 Conda，**建议安装体积占用较小的 Miniconda**，而不是较为庞大的 Anaconda；

  - Python 版本应为 **3.13+**

  - 需要安装的 Python 库：

    - **启动器依赖（必装！）**：

      `PyYAML`、`pathspec`

    - 部分脚本依赖的特色库（**参考后面的[「脚本列表」](#脚本列表)章节**中所写的依赖库，下一行仅为举例，不代表实际依赖）：

      `mss`（截图）、`Pillow`/`matplotlib`/`numpy`/`opencv-python`（图像处理）、`plotly`（图像可视化）、`PyMuPDF`/`pypdf`（PDF 处理）、`boto3`（S3 存储访问与上传）、`pynput`（键盘监听）

  - **一键安装 Python 库依赖：**

    - 大部分依赖库用以下命令即可：
      ```sh
      conda run -n base python -m pip install -r requirements.txt
      ```

    - 需要运行 `tools/research/` 下的脚本时，用以下命令安装专有依赖库：

      ```sh
      conda run -n base python -m pip install -r requirements-research.txt
      ```

    - 请勿安装 `requirements-internal.txt`；该文件仅供项目内部使用。

- **Windows：**

  - **仅支持 Windows 10 及以上版本的系统**；

  - 建议使用 **Scoop 包管理器**安装命令行工具，并使用 **WinGet 包管理器**安装图形界面工具；

    > **强烈不建议**通过手动下载可执行文件，并通过添加环境变量的方式管理命令行工具，这非常烦琐。
    > 交给包管理器可大大减少在这方面耗费的时间，还能做到自动检测更新！

  - 建议**安装 PowerShell 7**（不是系统自带的 PowerShell 5）

  - 部分脚本需要**在当前窗口中提权运行**，建议安装 **`gsudo`**（仅需运行 `scoop install gsudo`，项目：[https://github.com/gerardog/gsudo](https://github.com/gerardog/gsudo)）；否则只能从具有管理员权限的命令行中启动这些脚本；

  - 如需 Bash 支持，可**安装 Git**，启动器启动时会从 `git` 命令所在路径推导出 Git Bash 的所在路径；

    - 后续可能会加入通过 Cygwin 查找 Bash 的功能，并使其优先于通过 Git 查找 Bash。

- **macOS：**

  - 建议使用 **Homebrew 包管理器**安装命令行工具（Formulae）和图形界面工具（Cask）；
  - 部分工具（如 `macos/screen-utils`）仅支持配备 Apple Silicon 处理器的 Mac；

- **Linux：**

  - 如系统无图形界面，则部分涉及 GUI、截屏等功能的工具无法启动。
  - 部分涉及键盘钩子或截图的脚本，仅支持 X11，不支持 Wayland；Wayland 下启动器会将其隐藏。

- **其他：**

  - 推荐使用 **UniGetUI** 软件（[https://github.com/Devolutions/UniGetUI](https://github.com/Devolutions/UniGetUI)），以图形化方式管理系统包管理器，方便一键查找、安装、升级由包管理器安装的软件（支持 Windows 下的 Scoop/WinGet 和 macOS 下的 Homebrew）。
  - 如不清楚脚本的功能和原理，请借助 agent 来辅助使用。

- **环境变量**：

  - **建议将本路径加入到 `PATH` 环境变量中**，方便直接通过 `run-script.ps1` 或 `run-script.sh` 启动启动器；
  - 其他与启动器有关的环境变量请参考后面的[「如何使用启动器」](#如何使用启动器)章节。

- **各脚本所依赖的命令行工具和 Python 库：**

  - 参考后面[「脚本列表」](#脚本列表)章节中的表格，并建议通过**包管理器**安装对应的依赖工具和 Python 库。

    **参考安装命令（仅供参考，不可以直接复制粘贴运行）：**

    ```sh
    # Windows (scoop)
    scoop install ffmpeg yt-dlp aria2 smartmontools ghostscript
    
    # macOS (brew)
    brew install ffmpeg yt-dlp aria2 smartmontools ghostscript ntfs-3g
    brew install --cask macfuse
    
    # Linux (apt) 具体发行版和系统版本下，安装命令可能有差异，甚至需要添加自定义的软件源
    sudo apt install ffmpeg yt-dlp aria2 smartmontools ghostscript
    ```

### 项目结构

核心工具包：`utils/` — 将控制台、运行环境、系统、路径及交互职责拆分为独立类，并由 `utils/__init__.py` 统一导出公共工具。

- **所有工具脚本**都在 **`./tools/` 目录**中，如 `./tools/network`、`./tools/research`、`./tools/windows` 等；

  - 但查找或执行脚本时，应忽略 `tools` 这一级；如脚本 `./tools/network/rclone-sync.py`，启动时应直接输入 `network/rclone-sync.py` 或 `rclone-sync`。

- 所有 Python 脚本**均依赖 `./utils` 中的共享工具包**，其中包含交互式文本输入/路径输入、交互式菜单选择、路径处理、提权、依赖工具检查、ANSI ESC 命令行文本颜色等功能。

  > **不可以把功能脚本单独拿出来运行**，会因找不到 `utils` 中的依赖代码而报错！

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

- Windows 中执行 `run-script.ps1`，Linux/macOS 中执行 `run-script.sh`；包装脚本会查找可用的 Python 解释器，再启动真正的启动器 `run-script.py`。
- **无参数启动启动器**时，会先检测系统/平台/架构，并检测 Conda/Python/PowerShell/Bash 环境可用性；Linux 下还会显示当前图形环境（`no-gui`/`x11`/`wayland`）。检测完毕后，会**列出当前系统/平台/架构中支持的所有脚本**；列出所有脚本后通过键盘交互选择脚本并启动，支持参数透传：
  - 交互式选择支持**数字**或**脚本名称**（如 `15`、`macos/ntfs-3g-utils.py`、`ntfs-3g-utils`）
  - 将数字/名称后的参数**透传**给目标脚本（如 `15 --help`、`macos/screen-utils --list`、`screen-utils --list`）
- **有参数启动启动器**时，会根据参数自动查找脚本，并**透传剩余的参数**，此时不会打印出支持的脚本列表，直接启动目标脚本
  （如 `run-script.sh ntfs-3g-utils --list`，会自动找到 `macos/ntfs-3g-utils` 后执行，并透传 `--list` 参数到 `macos/ntfs-3g-utils` 中）
- 所有脚本**均支持省略父路径，直接输入脚本名**，如输入 `ntfs-3g-utils` 会自动递归查找此名称脚本，实际启动结果等价于输入 `macos/ntfs-3g-utils`。
  当不同目录中存在重名脚本时，会提示用户通过序号选择目标。
  - 注意：`tools` 这层应当忽略，启动器查找时是从 `./tools` 目录内部开始递归查找的
- 所有脚本均支持省略扩展名，如 `macos/ntfs-3g-utils.py` 可直接输入 `ntfs-3g-utils` 或 `macos/ntfs-3g-utils`。
  如遇到同名但扩展名不同的脚本，启动器会提示用户通过序号选择目标。
- **列出脚本时，可对指定平台/环境/架构隐藏部分脚本**：支持通过 `launcher-config.yaml` 设置系统平台（`windows`/`linux`/`macos`）、Linux 图形环境（`no-gui`/`x11`/`wayland`）和处理器架构（`x86`/`x86_64`/`armv7`/`arm64`），从而隐藏当前环境不支持的脚本。
  - 如需修改 `launcher-config.yaml`，请在项目根目录新建 `launcher-config.patch.yaml`，并在 patch 文件中仅写需要覆盖的设置项，启动器启动时会自动读取。
  - 解释器感知：无 `bash` 时隐藏 `.sh` 脚本；无 `pwsh` 时隐藏 `.ps1` 脚本
- **Test 分组默认关闭**。将 `launcher.test.enabled` 设置为 `true` 后，启动器会把配置的测试目录显示为独立的 `Test` 分组，并让其中的脚本参与裸名称查找；可使用 `test/<名称>` 或 `@test:<名称>` 精确指定测试脚本。
- 自动检测 Python：优先在 `./deps/python` 中查找打包的 Python，然后尽可能从 Conda 命令路径推导 base 环境中的 Python，再尝试已知路径和 `conda info --base`，最后回退到 `python3`
  - 可通过设置**系统环境变量 `ZL_CONDA_ENV`**来指定启动器执行脚本时使用的 **Conda 虚拟环境名称**，默认为 `base`。
- **`ZL_SCRIPT_ADDITIONAL_PATH`** 用于发现附加目录，环境变量名本身也可配置。
  多个目录使用平台路径分隔符分隔（Windows 为 `;`，macOS/Linux 为 `:`）；相对路径以项目根目录为基准。每个目录显示为 `─── Additional [N] ───`（N 从 1 开始），并应用相同的配置化忽略规则。
  配合 **`@N:` 前缀** 可精确指定脚本来源：`@0:` = 主目录，`@1:` = 第一个附加目录（对应 `Additional [1]`），依此类推。裸名递归搜索所有分组；`@N:` 将相同匹配规则限制到指定分组。多个有效匹配会以带编号的 `@N:` 路径列出。CLI 同样可用（如 `python run-script.py @1:test.py`）
- 已预留脚本打包、依赖打包功能（在 `./deps` 目录中放置依赖的二进制可执行文件），但还**没有完整实现并验证**，也不打算优先解决此问题。
  - 请勿启动 `compile-script.py`。
  - 启动器启动时，会从 `launcher-config.yaml` 读取 `extra-env-paths` 键，其中包含各平台启动脚本时要纳入 `PATH` 环境变量的路径，如 `./deps/python`、`./deps/bin` 等（方便日后摆脱 Conda 和包管理器）。该功能还没有经过验证，目前使用 Conda 和包管理器即可。

### 其他特性

- **交互输入相关：**

  - 多行输入使用 EOF 终止（Windows：`Ctrl+Z`、`Enter`；Linux/macOS：`Ctrl+D`）
  - **路径输入支持环境变量展开**（Linux/macOS：`$VAR`/`${VAR}`；Windows：`%VAR%`）
    （仅展开已定义的变量，未定义的变量保留原文）

  - 多路径输入提示支持通配符（`*`/`?`/`[abc]`）批量匹配文件；
    未匹配到文件的模式按原样字面路径处理

---

## 脚本列表

### PDF 工具

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/document-processing/pdf-compress.py` | 基于 Ghostscript 的 **PDF 压缩器**：<br />支持 Ebook（标准）和 Custom（自定义 DPI/质量）模式 | `ghostscript` |
| `tools/document-processing/pdf-decrypt.py` | **PDF 解密/编辑限制解除工具**：<br />可解密能够打开阅读、但编辑权限受保护的 PDF 文件。 | **Python 库**：`pypdf` |
| `tools/document-processing/pdf-bookmarks-add.py` | **扫描版 PDF 书籍目录注入工具**：<br />将目录截图逐页发送给**视觉 LLM（如 Qwen3-VL）生成指定格式的 JSON**（含页码/层级/编号/标题），再逐页粘贴到脚本中；脚本会立即校验每页数据，最后按输入顺序合并并写入 PDF。支持一个 PDF 页面对应 1、2 或 4 个连续书页，并可设置正文第 1 页在首个对应 PDF 页面中的对齐位置；自动添加一级 `Cover` 与 `Table of Contents` 书签。 | **Python 库**：`pypdf` |
| `tools/document-processing/document-screenshot.py` | **针对加密文档的自动截图抓取工具**：<br />基于模拟 PgDn 翻页 + 鼠标点击自动翻页，并通过自动截图来获取内容，适用于**全自动抓取并保存被 DRM 保护或位于加密 USB 存储设备中的 PDF** 文件内容。<br /><br />建议使用高分辨率屏幕，并将屏幕方向改为纵向，然后调整文档页面的显示范围（不超出屏幕范围并能充分利用屏幕空间）后，再用本脚本自动截图抓取。<br />macOS 中还需要额外授予相应的屏幕录制权限。 | **Windows/macOS/Linux X11**；不支持 Wayland<br />**Python 库**：`mss`、`pynput`、`Pillow` |
### 视频下载

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/download/download-bilibili.py` | **基于 BBDown 的 B 站视频下载器**：<br />（画质/仅音频/字幕/弹幕/多 API）<br />注：BBDown 已停止更新，后续会改用 yt-dlp 完成 B 站的下载 | `BBDown`、`ffmpeg`、`aria2`（可选） |
| `tools/download/download-yt.py`       | **基于 yt-dlp 的视频下载工具**：<br />（画质/音频/字幕/Cookies/播放列表） | `yt-dlp`、`ffmpeg`、`deno`（可选） |
| `tools/download/download-m3u8.py` | **基于 yt-dlp 的 m3u8/HLS 流媒体下载器**                     | `yt-dlp`、`ffmpeg`                  |

### 视频/图片编辑

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/multimedia/ffmpeg-crop-video.py` | **基于 FFmpeg 的视频裁剪工具**：<br />注意：并非画面裁剪，而是**按时间裁剪** | `ffmpeg`                                |
| `tools/research/batch-crop-images.py` | **基于 OpenCV 的批量图片裁剪工具**：<br />按画面 ROI 区域裁剪 | **Python 库**：`opencv-python`、`numpy` |

### 文件系统/磁盘挂载

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/filesystem/openssl-file-hash.py` | 基于 OpenSSL 的**文件哈希值计算工具**：<br />支持批量处理文件，并支持 `md5`、`sha256` 等 OpenSSL 提供的常见算法。 | `openssl` |
| `tools/filesystem/check-filename-overlong.py` | **长文件名自动截断工具**：<br />按 UTF-8 编码统计字节长度，自动截断超过指定字节数（默认 143，适配群晖的加密文件夹限制）的文件名。<br />截断时**保留扩展名**，若发生重名则在扩展名前自动加 `_1`、`_2` 等后缀 |  |
| `tools/filesystem/modify-file-time.py`        | **文件/文件夹时间戳修改工具**（创建/修改/访问时间），支持加入随机抖动，支持备份/还原指定文件夹下所有文件/文件夹的时间 |  |
| `tools/macos/ntfs-3g-utils.py`                | 仅 macOS，**基于 ntfs-3g-mac 的 NTFS 分区可写挂载工具**：<br />支持自动扫描 NTFS 分区，并支持卸载/弹出分区 | **仅 macOS**<br />**需要提权**<br />需在安全模式下允许来自认可开发者的内核扩展，并安装内核扩展 `macFUSE` 和挂载工具 `ntfs-3g-mac` |

### 文件系统/符号链接工具

| 脚本                                               | 描述                                                         | 依赖           |
| -------------------------------------------------- | ------------------------------------------------------------ | -------------- |
| `tools/filesystem/link-create.py`                  | **符号链接/硬链接创建工具**（Windows 下还支持生成目录软链接 SYMLINKD 和 JUNCTION）：<br />支持相对路径、镜像模式、冲突处理 |                |
| `tools/filesystem/link-scan.py`                    | **递归检测并打印目录中所有符号链接、硬链接的工具**（Windows 下还会打印目录软链接 SYMLINKD 和 JUNCTION）：<br />可自动检测死链（目标不存在），并提供自动修复或删除功能；Windows 下可将错误指向目录的文件软链接修复回 SYMLINKD。 |                |
| `tools/filesystem/link-fix-to-symlinkd-windows.py` | Windows 专用：将指向目录的文件软链接（SYMLINK）**修复**为正确的**目录软链接**（SYMLINKD）：<br />用于修复某些文件同步工具错误地按照 Linux 上的方法，不区分文件软链接和目录软链接，将目录软链接错误地弄成文件软链接，导致无法访问的问题。 | 仅 **Windows** |

### 文件系统/权限工具

| 脚本                                    | 描述                                                         | 依赖                     |
| --------------------------------------- | ------------------------------------------------------------ | ------------------------ |
| `tools/filesystem/batch-add-chmod-x.sh` | **Linux/macOS 下，批量给脚本文件添加可执行权限的工具**：<br />递归查找指定扩展名（默认 `.py`/`.sh`）的文件，并通过 `chmod +x` 添加可执行权限 | **Linux/macOS**<br />**需要提权** |
| `tools/filesystem/git-batch-add-chmod-x.ps1`       | **Windows 下，给 Git 仓库中的脚本文件批量添加可执行权限的工具**：<br />将 Git 暂存区中的 `.py`/`.sh` 文件通过 `git update-index --chmod=+x` 标记为可执行，方便跨平台开发时 Windows 端提交的文件在 Linux/macOS 上克隆后自带 `+x` 权限 | **Windows**<br />`git` |
| `tools/filesystem/remove-quarantine.py`      | 仅 macOS，**文件 quarantine 和 provenance 属性批量移除工具**（基于 `xattr` 命令） | **仅 macOS**             |

### 网络工具

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/network/tailscale-restart-accept-routes.py` | **Tailscale Subnet Route 功能快捷重启工具**：<br />通过切换 `--accept-routes` 开关重启 Tailscale 子网路由；<br />用于解决 macOS 中 Tailscale 开启 Subnet Route 后，设备回家再离家时该功能被自动关闭的问题 | `tailscale` |
| `tools/network/rclone-sync.py` | **使用个人 YAML 配置的 rclone 任务手动运行器**：<br />通过可复用 profile 和按机器匹配的子任务，同步、复制、移动或比较目录，也可复制和移动单个文件。支持配置校验、灵活的动作权限、操作与比较方式选择、删除限制、备选远端、参考性时间提示、试运行和取消操作。 | `rclone`<br />**Python 库**：`PyYAML` |
| `tools/network/upload-ipaddress.py` | **本机网卡信息收集上传工具：**<br />收集本机网卡信息，尤其是本机 IP 地址（基于 `ipconfig`/`ip addr`），并上传至 S3 存储桶，方便远程访问。<br />凭据来自环境变量：`ZL-IP-ADDRESS-S3-BUCKET`、`ZL-IP-ADDRESS-S3-ENDPOINT`、`ZL-IP-ADDRESS-S3-ID`、`ZL-IP-ADDRESS-S3-SECRET` | **Python 库：**`boto3` |
| `tools/windows/firewall-app-blocker.py` | 仅 Windows，**为 `.exe`/`.com` 文件配置系统防火墙断网规则的工具：**<br />支持**递归查找某路径下所有 `.exe`/`.com` 文件**，支持增加断网规则、删除断网规则（恢复原状）。 | **仅 Windows**<br />**需要提权** |
| `tools/network/webserver-run.py` | **将本地文件夹（或含 `index.html` 的网页目录）映射为本地 HTTP 服务的工具**：<br />使用基于 Python 内置 `http.server` 的多线程服务，支持交互模式（目录/绑定地址/端口）或 CLI（`--dir`、`--bind`、`--port`） |                                       |

### 打开方式

| 脚本                                | 描述                                                         | 依赖                                    |
| ----------------------------------- | ------------------------------------------------------------ | --------------------------------------- |
| `tools/windows/file-association.py` | 仅 Windows，**为指定扩展名的文件在系统中注册指定 EXE 作为打开方式的工具**：<br />可用于给一些便携软件注册对指定扩展名的打开方式 | **仅 Windows**<br />**需要提权** |
| `tools/macos/script-to-app.py`      | 仅 macOS，**将任意 Python 脚本打包为 macOS `.app` 包的工具**：<br />用于**将任意 Python 脚本作为文件的打开方式**，可自动加入 Python 依赖 | **仅 macOS** |
| `tools/windows/script-to-app.py` | 仅 Windows，针对任意 Python 脚本制作 CMD 启动器并放置到 `Program Files`：<br />用于**将任意 Python 脚本作为文件的打开方式**，可自动加入 Python 依赖 | **仅 Windows**<br />**需要提权** |

### 文本处理

| 脚本                            | 描述                                                         | 依赖                                 |
| ------------------------------- | ------------------------------------------------------------ | ------------------------------------ |
| `tools/parse-unicode-string.py` | **Unicode 字符信息显示工具**：<br />可获取输入文本中每个字符的序号、字符、十六进制、十进制、说明等信息，特殊字符（如控制符或空格等）有特殊标注格式。<br />支持用 `--clip`（剪贴板读取）参数从剪贴板读取文本，也可以使用常规的多行交互输入。 | Linux 剪贴板需 `wl-paste` 或 `xclip` |

### 显示器工具

| 脚本                                      | 描述                                                         | 依赖                                                         |
| ----------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| `tools/windows/show-screen-resolution.py` | 仅 Windows，**屏幕分辨率/缩放率查看工具**：<br />用于 RDP 连接中，解决设置界面中看不到当前远程电脑的屏幕分辨率和缩放率的问题。 | **仅 Windows**                                               |
| `tools/macos/screen-utils.py`             | 仅支持采用 Apple Silicon 的 macOS 设备，显示器管理工具 — 旋转、分辨率、亮度（内建 + 外接显示器 DDC/CI）、色彩模式诊断、外接显示器强制 RGB 输出覆写。<br />**特色功能**：**MacBook 连接外接显示器时，可一键开关笔记本自带屏幕**（`--toggle-built-in`）。**支持旋转显示器方向、修改外接显示器亮度**。<br />已在 macos 26.x tahoe 中验证可以正常使用。因其会调用 macos 的**私有 API**，不保证在其他版本系统中的可用性。 | **仅 macOS**（Apple Silicon）<br />**可选 Python 库**：`pyobjc-framework-Cocoa` |

### 隐私与清理

| 脚本                                          | 描述                                                         | 依赖                                                         |
| --------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| `tools/windows/clear-recycle-bin.py`          | 仅 Windows，**回收站强力清空工具**：<br />用于解决**回收站中存在 0 KB 文件/文件夹，但是无法清空**（清空后这些文件仍然存在于回收站中）的问题。<br />遇到符号链接，仅删除链接本身，不会遍历指向的目标。 | **仅 Windows**<br />**需要提权** |
| `tools/windows/clear-all-event-logs.py`       | 仅 Windows，**系统日志一键清空工具**<br />警告：删除后不可恢复。 | **仅 Windows**<br />**需要提权** |
| `tools/windows/clear-privacy.py`              | 仅 Windows，**隐私痕迹清除工具**：<br />（资源管理器历史、事件日志、DNS 缓存、浏览器数据、凭据、临时文件等），支持逐项确认。<br />警告：**使用风险自负。** | **仅 Windows**<br />**需要提权**                             |
| `tools/macos/clear-privacy.py`                | 仅 macOS，**隐私痕迹清除工具**：<br />（最近项目、访达状态、Shell 历史、浏览器数据、缓存、日志等），支持逐项确认。<br />警告：**使用风险自负。** | **仅 macOS**<br />可选 `brew install trash`<br />**需要提权** |
| `tools/filesystem/remove-os-junk-files.py`    | **系统生成垃圾文件递归删除工具**：<br />（`.DS_Store`、`__MACOSX__`、`Thumbs.db` 等） |                                                              |
| `tools/windows/clear-android-rndis-record.py` | 仅 Windows，**清理注册表中残留的 Android USB 网络共享/RNDIS 记录的工具**：<br />用于解决 Android 设备连接到电脑后，每次打开 USB 网络共享时，电脑中的**网络连接编号不断递增**的问题 | **仅 Windows**<br />**需要提权** |

### 系统工具

| 脚本                               | 描述                                                         | 依赖                                             |
| ---------------------------------- | ------------------------------------------------------------ | ------------------------------------------------ |
| `tools/windows/restart-service.py` | 仅 Windows，**系统服务强制重启工具**：<br />支持等待/不等待两种模式；内置 `Windows Audio` 预设，**可用于临时修复 RDP 远程桌面会话中，无法重定向被控方电脑声音的问题** | **仅 Windows**<br />**需要提权** |
| `tools/power-current.py`           | 充电器与电池遥测查看器，**可在 macOS 中查看当前电脑的充电功率**。<br />macOS 使用 `ioreg`，Windows 使用 PowerShell CIM/WMI，Linux 使用 `/sys/class/power_supply`。部分字段可能因固件/驱动限制不可用。（**本脚本仅在 macOS 中有最佳体验**） | **macOS 中体验最佳**，也支持其他系统（数据不全） |
| `tools/disk-smart-info.py`         | 基于 smartmontools 的**磁盘健康信息查看器**：<br />列出 SMART 磁盘并显示详细属性（写入量、通电时间、剩余寿命等） | `smartmontools` |

### 软件启动

| 脚本                        | 描述                                                         | 依赖         |
| --------------------------- | ------------------------------------------------------------ | ------------ |
| `tools/macos/run-pdf2zh.sh` | 仅 macOS，**启动 pdf2zh-next**（[PDFMathTranslate-next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next)） | **仅 macOS** |

### 预设命令

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/run-commands.py` | **预设命令运行器**：<br />选择自己的配置文件，再通过菜单选择并执行保存的命令或脚本；[配置样例](tools/run-commands-schema-sample.yaml) 提供详细说明。 | **Python 库**：`PyYAML`；预设命令所需的程序或解释器 |

### 科研工具

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/research/npy-viewer.py` | **`.npy`/`.npz` 文件交互式查看器**：<br />1D 折线/柱状/散点图，2D 热力图/曲面图 | **Python 库**：`numpy`、`matplotlib`、`plotly` |
| `tools/research/pattern-generator.py` | **结构光投影图案生成器**：<br />生成可选择左/上边缘、像素中心或右/下边缘采样的正弦条纹，以及标准格雷码序列。<br />非专业人员请勿使用 | Python 库：`opencv-python`、`numpy` |

### 测试/辅助脚本

| 脚本 | 描述 | 依赖 |
|------|------|------|
| `tools/keyboard-hook-viewer.py` | **全局键盘鼠标钩子监控器**：<br />macOS 使用 CGEvent tap 与 IOHID（可显示事件来源设备 ID）；Windows 使用 ctypes 调用 `SetWindowsHookEx`；Linux 使用 X11 XRecord | **Windows/macOS/Linux X11**；不支持 Wayland<br />macOS：`pip install pyobjc-framework-Quartz`<br />Linux：`pip install python-xlib`<br />Windows：无（标准库 ctypes） |
| `test/print-argv.py`<br>`test/print-argv.sh`<br>`test/print-argv.ps1` | **命令行参数打印工具**：<br />可打印出所有传入脚本的 argv 参数，用于判断脚本传入参数是否正确 |  |
