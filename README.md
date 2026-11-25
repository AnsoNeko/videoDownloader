# Video Fetcher

本地视频下载工具，支持抖音、B站、小红书、YouTube、X（Twitter）和 Instagram。

## 功能

- 解析视频链接，可选择清晰度、仅视频或仅音频。
- 支持音视频合并、自定义下载目录和下载进度显示。
- 平台需要登录时，可导入或粘贴 Cookie。

## 环境要求

- Windows x64、PowerShell、64 位 Python 3.10 或更高版本（含 pip）。
- 下载 YouTube 需要 Deno 2.3+ 或 Node.js 22+。可通过 PATH 使用，或放在 `tools/deno/deno.exe` 或 `tools/node/node.exe`。
- 合并音视频需要 FFmpeg。将 `ffmpeg.exe` 和 `ffprobe.exe` 放入 `tools/ffmpeg/bin/`，或将这两个工具所在的目录加入 PATH。

## 从源码运行

在项目根目录执行以下命令。

```powershell
powershell -ExecutionPolicy Bypass -File .\update_dependencies.ps1
python app.py
```

打开 [http://127.0.0.1:5000](http://127.0.0.1:5000)。下载文件默认保存在 `downloads/`。

## 构建 Windows 便携版

构建前，将 FFmpeg 和所选的 JavaScript 运行时放到上面列出的 `tools/` 路径，并关闭正在运行的 Video Fetcher。然后在项目根目录执行以下命令。

```powershell
python -m venv .runtime\package-venv
.\.runtime\package-venv\Scripts\python.exe -m pip install --pre -r requirements.txt pyinstaller websocket-client
powershell -ExecutionPolicy Bypass -File .\package_windows.ps1
```

构建完成后，运行 `dist/updated/VideoFetcher/VideoFetcher.exe`。分发时请保留整个 `VideoFetcher` 目录。
