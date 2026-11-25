# Video Fetcher

本地视频下载工具，支持抖音、B站、小红书、YouTube、X（Twitter）和 Instagram。

## Windows 下载

从 [GitHub Releases](https://github.com/AnsoNeko/videoDownloader/releases/latest) 下载 Windows x64 ZIP 和对应的 `.sha256` 校验文件。完整解压 ZIP 后，运行 `VideoFetcher/VideoFetcher.exe`，再打开 http://127.0.0.1:5000。

2026-11-09 版本修复了 YouTube 格式列表在高分辨率选项排在后面时可能漏掉这些选项的问题，内含 Node.js 和 FFmpeg。

## 启动与更新

需要 Python 3.10+。在项目目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\update_dependencies.ps1
python app.py
```

打开 http://127.0.0.1:5000，解析链接后选择格式下载。文件保存到 `downloads/`。
页面中的“下载文件夹”支持输入完整路径或点击“选择文件夹”打开 Windows 目录选择窗口。
点击“保存目录”或开始下载时会记住路径，重启后仍有效；“恢复默认”改回程序目录下的 `downloads/`。
目录不存在时会自动创建；路径不可写时会提示错误。每个下载任务使用创建时的目录。
Cookies 输入区的“安装 Cookies 获取插件”按钮会在新标签页打开 Get cookies.txt LOCALLY 的 Chrome 商店安装页。
更新后需要重启程序；已打包的 EXE 需要重新构建，单独更新 vendor 不会更新 EXE。

## 抖音、B站和小红书

可粘贴单作品链接或带链接的分享文案，支持 `v.douyin.com`、`b23.tv`、
`xhslink.com` 短链。抖音也支持 `iesdouyin.com/share/video/` 与带 `modal_id`
的链接。小红书支持 `explore/`、`discovery/item/`，会保留 `xsec_token` 和
`xsec_source`；建议直接复制完整分享链接，删除这些参数可能导致无法访问。

抖音使用参考项目中的 a_bogus 签名算法请求作品详情，并保留 yt-dlp 原生解析和
页面内嵌数据作为后备。B站和小红书复用 yt-dlp 的格式解析和下载，继续支持
格式选择、下载目录、进度以及 FFmpeg 音视频合并。只下载视频，图文作品不会被当作视频下载。
签名代码与来源、许可证见 `THIRD_PARTY_NOTICES.md`；无需运行参考项目或新增 Python 依赖。

## Cookie 常驻可选配置

Cookie 输入区始终显示。首次使用直接粘贴或导入 Cookie，即可自动识别所属平台并点击
“保存 Cookie”，无需先填视频链接或手动选平台；也支持粘贴链接后自动切换平台。
Netscape 文件按域名识别，原始 Cookie 按平台特有字段识别；只有 `sessionid` 等通用字段
或同时包含多个平台时，会提示手动选择，也可通过对应视频链接辅助判断。
各平台输入草稿相互隔离，自动识别切换时保留刚粘贴的内容。
支持导入 Netscape 格式 `cookies.txt`，也支持直接粘贴浏览器请求头的
`Cookie: name=value; name2=value2` 或其中的值。

使用顺序为：当前输入内容 → 当前平台已保存的 Cookie → 程序目录 `cookies.txt`
中匹配当前平台域名的条目。原始请求头只赋予当前平台域名；短链不会把登录 Cookie
发送给 `xhslink.com`、`b23.tv` 等短链服务。全局 `cookies.txt` 必须有 Netscape
域名字段，不能放没有域名的原始请求头。Cookie 不会被拼入全局 HTTP 请求头。

点击“保存 Cookie”后，才会将输入保存到 `.auth/cookies/<平台>.txt`，
重启后可继续使用；这是本机明文文件，请保管好程序目录。状态接口只返回是否已保存。
“清除此平台 Cookie”会删除该平台的保存文件、清空输入，并关闭自动使用；
程序目录的旧 `cookies.txt` 保留。留空并取消“自动使用”即可不带 Cookie 尝试。
下载任务在创建时固定本次 Cookie，之后修改设置不会影响已经创建的任务。

抖音和小红书经常要求新的 Cookie；B站高清格式取决于登录状态及账号权限。
Cookie 保持可选，不保证匿名可下载每条视频。遇到平台验证码、访问限制或限流时，
请在浏览器完成验证或稍后重试；这些错误不会直接被判定为 Cookie 失效。

## YouTube 依赖

使用官方 [yt-dlp](https://github.com/yt-dlp/yt-dlp) Python API。
按官方建议使用 nightly，并通过 `yt-dlp[default]` 同步安装匹配的 EJS 解题组件。
本次最低版本为 `2026.10.10.233141.dev0`；更新脚本使用 `--upgrade --pre` 获取兼容的新版本。

YouTube 还需要 **Deno >= 2.3**（优先）或 **Node.js >= 22**。
安装后放入 PATH，或分别放在 `tools/deno/deno.exe`、`tools/node/node.exe`。
程序会检测版本并显式启用可用运行时，不再强制使用需要额外 PO Token 的 mweb 客户端。
依赖状态与 yt-dlp 版本可在 `/api/state` 查看。
配置依据：[官方 EJS 指南](https://github.com/yt-dlp/yt-dlp/wiki/EJS)。

高清下载需要 FFmpeg 合并音视频。将 `ffmpeg.exe` 和 `ffprobe.exe` 放入
`tools/ffmpeg/bin/`，也可以安装到 PATH。缺少 FFmpeg 时仅选择同时包含音视频的格式。
手动选择“仅视频”或“仅音频”格式时，按所选格式下载。

公开视频通常无需登录。如果 YouTube 要求登录验证，可将自己导出的 Netscape 格式
`cookies.txt` 粘贴到页面，或放在程序目录。粘贴内容优先；Cookie 失效时应重新导出。
程序保留 Cookie 的域名范围，不将其注入全局 HTTP 请求头。
网络环境需要能够访问 YouTube；登录验证、地区限制和不可用视频会返回实际错误。

## 验证

```powershell
python -m unittest discover -s tests -v
```

当前包含 58 项测试，覆盖平台链接规范化、短链跳转、签名参数一致性、Cookie 自动识别/保存/
清除/域名隔离/禁用/任务快照、错误分类，以及原有 YouTube 和下载目录功能。
下载测试用 FFmpeg 生成真实 MP4，由本地 HTTP 服务发送，经过三平台下载任务验证
文件内容及完成进度；平台元数据使用受控样例，不等同于真实账号访问验收。

2026-10-26 现场验证：B站匿名解析返回 15 个格式；抖音匿名签名请求返回 HTTP 403，
小红书无 Cookie、无分享令牌的测试未返回视频流。已检查页面自动选平台、Cookie 保存反馈、
平台切换隔离和浏览器控制台。尚未用真实登录 Cookie 完成抖音/小红书下载。
Cookie 自动识别补充验证：已在隔离页面验证无链接直接粘贴/保存、替换 Cookie 自动切换且
保留原文、通用字段提示选择，以及链接辅助识别保存；47 项测试通过。

## Windows 打包

先更新依赖，准备上述 tools 目录中的工具，然后运行：

```powershell
python -m venv .runtime/package-venv
.\.runtime\package-venv\Scripts\python.exe -m pip install --pre -r requirements.txt pyinstaller websocket-client
powershell -ExecutionPolicy Bypass -File .\package_windows.ps1
```

`VideoFetcher.spec` 会收集 yt-dlp 与 EJS 资源。运行 `dist/updated/VideoFetcher/VideoFetcher.exe`。
更新前先关闭程序。打包脚本先在临时目录构建，再更新程序文件，保留下载、Cookies 和目录设置。
分发到没有 Node.js/Deno 的电脑时，需要将运行时放入 tools 后重新打包。

2026-10-26 已生成最新版 `dist/VideoFetcher-20261026-windows-x64.zip`（131,258,802 字节），
包含最新三平台下载、Cookie 自动识别功能和 Node.js/FFmpeg，附带 `.sha256` 校验文件。
完整解压后运行 `VideoFetcher/VideoFetcher.exe`；本机更新目录仍为 `dist/updated/VideoFetcher/`。
ZIP 来自干净的构建目录，不含个人 Cookie、下载或设置，共 193 个文件；已通过 CRC 检查及构建文件内容摘要核对。
打包环境 47 项测试、依赖检查通过；隔离成品启动、Cookie 无链接识别/保存/重启读取/清除、
B站真实匿名解析（15 个格式）通过；现有用户文件摘要保持一致。EXE 为 `NotSigned`。
隔离测试的临时目录清理被自动审批策略拦截，残留目录保留在 `.runtime/`，未包含在 ZIP 中。

Cookie 兼容性修复版：`dist/VideoFetcher-20261026-cookie-fix-windows-x64.zip`。
部分浏览器复制的 Cookie 可能带有 `=…` 空名称条目，现会忽略这些条目并保留其余具名
Cookie 及原值，同时保留 Netscape 文件末尾的空值。此前“Cookie 名称不正确”是本地格式
检查提示，不代表平台判定 Cookie 已失效。修复后 50 项测试、附件本地回归和隔离成品的
识别/保存/重启/清除验证通过；本轮未将附件 Cookie 发送到平台，未验证其线上有效性。

抖音设备签名修复版：`dist/VideoFetcher-20261026-douyin-fix-windows-x64.zip`。
旧版详情请求缺少与 Cookie 绑定的 UIFID、指纹和 `x-secsdk-web-signature`，会收到
`ArgusSecurityPlugin Uifid Not Found` 的 HTTP 403；这类拒绝现在单独归为设备签名问题，
不会直接判定 Cookie 失效。请求使用同一 Cookie 中的身份字段，签名后的查询字节原样发送，
并保留公开分享页后备解析。真正的登录拒绝、通用 403 和限流不会触发其他接口重试。
错误提示清除终端颜色控制字符，并脱敏设备身份、指纹及签名查询参数。
依据：[上游 Web SDK 签名实现](https://github.com/Evil0ctal/Douyin_TikTok_Download_API/blob/main/src/dtk/signing/native/websign.py)。

现场使用用户提供的 Cookie 与视频 `7700648334486383963` 验证：解析返回 54 个格式，
完整下载 39,817,128 字节 MP4；FFprobe 确认视频 1280×714 且含音轨。Cookie 原文未写入
源码、日志或分发包；57 项回归测试通过。以上是本条作品的实际结果，不代表其他账号或作品
在遇到验证码、访问权限或平台变化时也一定可下载。

小红书/B站补充实测（同一 `douyin-fix` 成品，无需重新打包）：

- 小红书：使用用户提供的 Cookie 和完整分享链接，作品 `6adafbbe000000002c00fb42`
  解析返回 8 个格式；成品 EXE 完整下载 937,236 字节 MP4，FFprobe 确认
  1080×1350 视频及音轨，时长约 2.856 秒，任务进度 100%。Cookie 仅用于当次请求，
  未保存到成品的 Cookie 配置；验证输入用的临时 Cookie 文件已清除。
- B站：匿名验证分P链接 `BV1bK411W797?p=1`；成品 EXE 解析返回 12 个格式，
  下载并合并 2,857,929 字节 MP4，FFprobe 确认 640×360 视频及音轨，
  时长约 90.302 秒，任务进度 100%。没有提供 B站登录 Cookie，因此登录态高清/VIP 权限未验收。

以上均为实际平台请求和实际文件下载，非受控样例；下载证据及脱敏摘要留在 `.runtime/`。
