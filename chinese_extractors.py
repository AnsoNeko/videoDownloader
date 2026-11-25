"""Small yt-dlp adapters for Chinese platform share links and webpage data.

Uses the same downloader and domain-scoped cookie jar as the standard extractors.
Reference projects are consulted for URL and media field shapes; no external
checkout, service, browser session, or signing dependency is required at runtime.
"""
from __future__ import annotations

import hashlib
import time
from urllib.parse import quote, unquote, urlencode

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.extractor.tiktok import DouyinIE
from yt_dlp.extractor.xiaohongshu import XiaoHongShuIE
from yt_dlp.utils import ExtractorError, js_to_json
from yt_dlp.networking.exceptions import HTTPError

from platform_support import infer_platform_key, normalize_supported_url
from third_party.douyin_abogus import ABogus


DOUYIN_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"
DOUYIN_MOBILE_USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
# SDK project 34; upstream algorithm reference, not a user credential:
# https://github.com/Evil0ctal/Douyin_TikTok_Download_API/blob/main/src/dtk/signing/native/websign.py
DOUYIN_WEB_SIGN_SALT = "A96D855A08C0A9707F8BEF0D9A527E4E"


def signed_douyin_params(video_id):
    # Keep the signed and transmitted dictionaries identical. The reference
    # signer uses a fixed Chrome 90 UA code and an explicitly empty msToken.
    params = {
        "device_platform": "webapp", "aid": "6383", "channel": "channel_pc_web",
        "pc_client_type": "1", "version_code": "290100", "version_name": "29.1.0",
        "cookie_enabled": "true", "screen_width": "1920", "screen_height": "1080",
        "browser_language": "zh-CN", "browser_platform": "Win32", "browser_name": "Chrome",
        "browser_version": "90.0.4430.212", "browser_online": "true", "engine_name": "Blink",
        "engine_version": "90.0.4430.212", "os_name": "Windows", "os_version": "10",
        "cpu_core_num": "12", "device_memory": "8", "platform": "PC",
        "aweme_id": video_id, "msToken": "",
    }
    params["a_bogus"] = ABogus().get_value(params)
    return params


def signed_douyin_request(video_id, cookies, timestamp=None):
    params = signed_douyin_params(video_id)
    headers = {'User-Agent': DOUYIN_USER_AGENT, 'Referer': f'https://www.douyin.com/video/{video_id}',
               'Accept': 'application/json, text/plain, */*', 'Accept-Language': 'zh-CN,zh;q=0.9'}
    uifid = next((cookies.get(name) for name in ('UIFID', 'UIFID_TEMP', 'uifid', 'uifid_temp') if cookies.get(name)), None)
    if uifid:
        if cookies.get('s_v_web_id'):
            params['verifyFp'] = params['fp'] = cookies['s_v_web_id']
        params['uifid'] = uifid
        params['timestamp'] = str(int(time.time() if timestamp is None else timestamp))
        covered = urlencode(params, quote_via=quote, safe='*-._').replace('~', '%7E')
        signature = hashlib.md5(f"{uifid}_{params['timestamp']}_{DOUYIN_WEB_SIGN_SALT}_{covered}".encode()).hexdigest()
        # Send the exact covered bytes; reconstructing query= here can change
        # escaping/order and invalidate the SDK signature.
        query = covered + '&x-secsdk-web-signature=' + signature
        headers.update({'uifid': uifid, 'x-secsdk-web-signature': signature,
                        'x-secsdk-web-expire': params['timestamp']})
    else:
        query = urlencode(params)
    return 'https://www.douyin.com/aweme/v1/web/aweme/detail/?' + query, headers


class DouyinSignatureError(ExtractorError):
    """A confirmed device-signature rejection, distinct from a login/captcha."""


def find_aweme(data, video_id):
    """Only accept the requested video, never a recommended neighbouring item."""
    if isinstance(data, dict):
        identity = data.get("aweme_id") or data.get("awemeId")
        if str(identity) == video_id and isinstance(data.get("video"), dict):
            return data
        for value in data.values():
            result = find_aweme(value, video_id)
            if result:
                return result
    elif isinstance(data, list):
        for value in data:
            result = find_aweme(value, video_id)
            if result:
                return result
    return None


class FetcherShareIE(InfoExtractor):
    _VALID_URL = r'https?://(?:v\.douyin\.com|(?:www\.)?(?:xhslink\.com|b23\.tv))/(?P<id>[^?#]+)'

    def _real_extract(self, url):
        platform = infer_platform_key(url)
        _, response = self._download_webpage_handle(url, self._match_id(url), note="Resolving share link")
        resolved = normalize_supported_url(response.url)
        if infer_platform_key(resolved) != platform or self.suitable(resolved):
            raise ExtractorError("短链接未跳转到有效作品页，请从浏览器复制完整作品链接。", expected=True)
        key = {"douyin": FetcherDouyinIE.ie_key(), "xiaohongshu": FetcherXhsIE.ie_key()}.get(platform)
        return self.url_result(resolved, ie=key)


class FetcherDouyinIE(DouyinIE):
    """Signed detail API, native extractor, then matching embedded page data."""

    def _signed_detail(self, video_id):
        cookies = {name: item.value for name, item in self._get_cookies(self._WEBPAGE_HOST).items()}
        request_url, headers = signed_douyin_request(video_id, cookies)
        try:
            data = self._download_json(
                request_url, video_id, note='Downloading signed Douyin detail', headers=headers)
        except ExtractorError as exc:
            if isinstance(exc.cause, HTTPError) and exc.cause.status in {401, 403, 418, 429}:
                if exc.cause.status == 403:
                    body = exc.cause.response.read(4096).decode('utf-8', 'replace').lower()
                    reasons = ('uifid not found', 'signature not found', 'sign invalid', 'sign expired')
                    reason = next((marker for marker in reasons if marker in body), None)
                    if 'argussecurityplugin' in body and reason:
                        raise DouyinSignatureError(
                            f'抖音设备签名校验未通过（HTTP 403，{reason}），这不等同于 Cookie 失效。', expected=True) from None
                raise
            return None
        if data.get("status_code") in {8, 14, 10008, 2190008}:
            raise ExtractorError("抖音登录失效，请更新 Cookie。", expected=True)
        return find_aweme(data.get("aweme_detail"), video_id)

    def _parse_detail(self, detail):
        video = detail.get("video") or {}
        addresses = [video.get(key) for key in ("play_addr", "play_addr_h264", "play_addr_bytevc1", "download_addr")]
        addresses.extend(rate.get("play_addr") for rate in video.get("bit_rate") or [])
        if not any((address or {}).get("url_list") for address in addresses):
            raise ExtractorError("该抖音作品没有可下载的视频流，可能是图文作品。", expected=True)
        info = self._parse_aweme_video_app(detail)
        info["http_headers"] = {"Referer": "https://www.douyin.com/", "User-Agent": DOUYIN_USER_AGENT}
        return info

    def _real_extract(self, url):
        video_id = self._match_id(url)
        try:
            detail = self._signed_detail(video_id)
        except DouyinSignatureError:
            detail = self._page_detail(video_id)
            if detail:
                return self._parse_detail(detail)
            raise
        if detail:
            return self._parse_detail(detail)
        try:
            info = super()._real_extract(url)
            if not any(fmt.get("vcodec") != "none" for fmt in info.get("formats") or []):
                raise ExtractorError("该抖音作品没有可下载的视频流，可能是图文作品。", expected=True)
            info["http_headers"] = {"Referer": "https://www.douyin.com/"}
            return info
        except ExtractorError as api_error:
            if isinstance(api_error.cause, HTTPError) and api_error.cause.status in {401, 403, 418, 429}:
                raise
            detail = self._page_detail(video_id)
            if detail:
                return self._parse_detail(detail)
            raise api_error

    def _page_detail(self, video_id):
        pages = ((f'https://www.douyin.com/share/video/{video_id}/', DOUYIN_MOBILE_USER_AGENT),
                 (f'https://www.douyin.com/video/{video_id}', DOUYIN_USER_AGENT),
                 (f'https://www.iesdouyin.com/share/video/{video_id}/', DOUYIN_MOBILE_USER_AGENT))
        for page_url, user_agent in pages:
            webpage = self._download_webpage(page_url, video_id, fatal=False, headers={'User-Agent': user_agent})
            if not webpage:
                continue
            states = [self._search_json(
                r'window\._ROUTER_DATA\s*=', webpage, 'router data', video_id,
                transform_source=js_to_json, default={})]
            render_data = self._search_regex(
                r'<script[^>]+id=[\"\']RENDER_DATA[\"\'][^>]*>([^<]+)',
                webpage, 'render data', default=None)
            if render_data:
                states.append(self._parse_json(unquote(render_data), video_id, fatal=False))
            for state in states:
                detail = find_aweme(state, video_id)
                if detail:
                    return detail
        return None


class FetcherXhsIE(XiaoHongShuIE):
    def _real_extract(self, url):
        info = super()._real_extract(url)
        if not info.get("formats"):
            raise ExtractorError("该小红书笔记没有可下载的视频流，可能是图文笔记或当前登录状态不可访问。", expected=True)
        durations = [fmt["duration"] for fmt in info["formats"] if fmt.get("duration")]
        if durations:
            info["duration"] = max(durations)
        info["http_headers"] = {"Referer": url}
        return info


def extract_platform_info(ydl, url, download):
    # Explicit keys ensure these adapters take precedence over built-in extractors.
    if FetcherShareIE.suitable(url):
        key = FetcherShareIE.ie_key()
    elif FetcherDouyinIE.suitable(url):
        key = FetcherDouyinIE.ie_key()
    elif FetcherXhsIE.suitable(url):
        key = FetcherXhsIE.ie_key()
    else:
        return ydl.extract_info(url, download=download)
    for extractor in (FetcherShareIE, FetcherDouyinIE, FetcherXhsIE):
        ydl.add_info_extractor(extractor())
    return ydl.extract_info(url, download=download, ie_key=key)
