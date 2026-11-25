# Third-party platform support

`third_party/douyin_abogus.py` is reused from the supplied ToolBox reference
(`backend/app/collectors/signing/douyin_abogus.py`). It uses Python's standard
library `hashlib` implementation of SM3 rather than requiring gmssl.
Its original attribution and license header are retained unchanged.

The header identifies JoeanAmier's
[TikTokDownloader](https://github.com/JoeanAmier/TikTokDownloader) as the original
source under GNU GPL v3, and modifications from Evil0ctal's
[Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API)
under Apache 2.0 while retaining that original attribution.
Both license texts are included in `third_party/`. These notices and license
texts are included by the Windows packaging specification.

The visitor-bound Web SDK request signature follows the algorithm documented in
the same upstream project's
[`src/dtk/signing/native/websign.py`](https://github.com/Evil0ctal/Douyin_TikTok_Download_API/blob/main/src/dtk/signing/native/websign.py).
The implementation uses the supplied cookie jar's own visitor identifier and
fingerprint, and signs the exact query bytes sent to the detail endpoint.

URL and media-field handling was also informed by the supplied Spider_XHS and
ToolBox collectors. Their packages and services are not required at runtime.
The existing yt-dlp dependency provides Bilibili and Xiaohongshu extraction,
format selection, cookie jars, progress reporting and media downloads.
