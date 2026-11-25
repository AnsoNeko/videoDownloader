import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote

import app
from chinese_extractors import FetcherDouyinIE, FetcherShareIE, FetcherXhsIE, find_aweme
from yt_dlp.extractor.tiktok import DouyinIE
from yt_dlp.utils import ExtractorError


DOUYIN = "https://www.douyin.com/video/7491525659865720347"
XHS = "https://www.xiaohongshu.com/explore/674051740000000007027a15?xsec_token=dummy%2Btoken%3D&xsec_source=pc_share"
BILI = "https://www.bilibili.com/video/BV1EQQUBYEEB"


class PlatformTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name, value in (("AUTH_DIR", self.root / "auth"), ("RUNTIME_DIR", self.root),
                            ("SETTINGS_PATH", self.root / "settings.json"), ("DOWNLOADS_DIR", self.root)):
            mocked = patch.object(app, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        mocked = patch.object(app, "detect_cookie_file", return_value=None)
        mocked.start()
        self.addCleanup(mocked.stop)
        self.client = app.app.test_client()

    def test_share_text_and_canonical_urls(self):
        cases = {
            "点击看看 https://v.douyin.com/AbCdEf/，复制打开抖音": "https://v.douyin.com/AbCdEf/",
            "https://www.iesdouyin.com/share/video/123456/?region=CN": "https://www.douyin.com/video/123456",
            "https://www.douyin.com/user/author?modal_id=123456": "https://www.douyin.com/video/123456",
            "https://www.douyin.com/?aweme_id=123456": "https://www.douyin.com/video/123456",
            "https://xiaohongshu.com/discovery/item/674051740000000007027a15?xsec_token=dummy%2Btoken%3D&xsec_source=pc_share": XHS,
            "来看看 http://xhslink.com/a/ABC，打开小红书": "http://xhslink.com/a/ABC",
            "【视频】https://b23.tv/abcdef。": "https://b23.tv/abcdef",
        }
        for original, expected in cases.items():
            with self.subTest(original=original):
                self.assertEqual(app.validate_url(original), expected)

    def test_host_validation_rejects_impersonation(self):
        for url in ("https://douyin.com.evil.test/video/1", "https://evil.test/?url=https://bilibili.com/video/1",
                    "https://douyin.com@127.0.0.1/video/1", "file:///douyin.com/video/1", "https://www.douyin.com:8000/video/1", 12):
            with self.subTest(url=url), self.assertRaises(ValueError):
                app.validate_url(url)

    def test_raw_cookie_scopes_for_short_links(self):
        for url, domain in (("https://v.douyin.com/test", ".douyin.com"),
                            ("http://xhslink.com/a/test", ".xiaohongshu.com"),
                            ("https://b23.tv/test", ".bilibili.com")):
            result = app.normalize_cookie_text("Cookie: sessionid=dummy; token=a=b", url)
            self.assertEqual(result.count(domain + "\t"), 2)
            self.assertNotIn(".xhslink.com", result)
            self.assertNotIn(".b23.tv", result)
            self.assertIn("token\ta=b", result)

    def test_saved_cookie_lifecycle_and_platform_isolation(self):
        for key in ("douyin", "xiaohongshu", "bilibili"):
            result = self.client.post("/api/cookies", json={"platform": key, "cookies_text": f"sessionid=dummy-{key}"})
            self.assertEqual(result.status_code, 200)
            self.assertTrue(result.json["saved_cookies"][key])
            self.assertNotIn("dummy-", result.get_data(as_text=True))
        for url, key in ((DOUYIN, "douyin"), (XHS, "xiaohongshu"), (BILI, "bilibili")):
            text = app.resolve_cookie_text(url, "")
            self.assertIn(f"dummy-{key}", text)
            self.assertEqual(text.count("dummy-"), 1)
            self.assertIn("override", app.resolve_cookie_text(url, "sessionid=override"))
            self.assertEqual(app.resolve_cookie_text(url, "", False), "")
        self.assertFalse(self.client.get("/api/state").json["saved_cookies"]["youtube"])
        self.assertEqual(self.client.delete("/api/cookies/douyin").status_code, 200)
        self.assertEqual(app.resolve_cookie_text(DOUYIN, ""), "")
        self.assertIn("dummy-xiaohongshu", app.resolve_cookie_text(XHS, ""))

    def test_bad_cookie_never_replaces_saved_or_leaks_values(self):
        app.save_platform_cookies("douyin", "sessionid=old-value")
        for text in ("secret-broken-cookie", ".douyin.com\tTRUE\t/\tTRUE\tinvalid\tsessionid\tsecret-value",
                     "sessionid=secret-value\nOther-Header: value", 42):
            result = self.client.post("/api/cookies", json={"platform": "douyin", "cookies_text": text})
            self.assertEqual(result.status_code, 400)
            self.assertNotIn("secret-", result.get_data(as_text=True))
        self.assertIn("old-value", app.resolve_cookie_text(DOUYIN, ""))
        self.assertEqual(self.client.post("/api/cookies", json={"platform": "../outside", "cookies_text": "key=value"}).status_code, 400)

    def test_combined_file_filters_domains_and_preserves_httponly(self):
        cookie_file = self.root / "cookies.txt"
        cookie_file.write_text("# Netscape HTTP Cookie File\n"
                               "#HttpOnly_.douyin.com\tTRUE\t/\tTRUE\t0\tsessionid\tdouyin-dummy\n"
                               ".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tbili-dummy\n", encoding="utf-8")
        with patch.object(app, "detect_cookie_file", return_value=cookie_file):
            self.assertIn("#HttpOnly_.douyin.com", app.resolve_cookie_text(DOUYIN, ""))
            self.assertNotIn("bili-dummy", app.resolve_cookie_text(DOUYIN, ""))
            self.assertIn("bili-dummy", app.resolve_cookie_text(BILI, ""))
            self.assertEqual(app.resolve_cookie_text(XHS, ""), "")
            cookie_file.write_text("sessionid=unscoped-global-secret")
            self.assertEqual(app.resolve_cookie_text(XHS, ""), "")

    def test_cookie_optional_and_disabled_during_preview_and_download(self):
        app.save_platform_cookies("douyin", "sessionid=saved-value")
        with patch.object(app, "extract_platform_info", return_value={"title": "fixture", "formats": []}) as extract:
            with patch.object(app.yt_dlp, "YoutubeDL") as factory:
                response = self.client.post("/api/info", json={"url": DOUYIN, "use_saved_cookies": False, "use_browser_cookies": False})
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(factory.call_args.args[0]["cookiefile"])
                extract.assert_called_once()
        with patch.object(app.threading, "Thread") as worker:
            response = self.client.post("/api/download", json={"url": DOUYIN, "use_saved_cookies": False})
            self.addCleanup(app.DOWNLOAD_JOBS.pop, response.json["job_id"], None)
            self.assertEqual(worker.call_args.kwargs["args"][4], "")
            self.assertFalse(worker.call_args.kwargs["kwargs"]["use_saved_cookies"])

    def test_download_takes_cookie_snapshot_and_never_exposes_it(self):
        app.save_platform_cookies("douyin", "sessionid=before-queue")
        with patch.object(app.threading, "Thread") as worker:
            response = self.client.post("/api/download", json={"url": DOUYIN})
            self.assertEqual(response.status_code, 200)
            job_id = response.json["job_id"]
            self.addCleanup(app.DOWNLOAD_JOBS.pop, job_id, None)
            app.save_platform_cookies("douyin", "sessionid=after-queue")
            self.assertIn("before-queue", worker.call_args.kwargs["args"][4])
            self.assertNotIn("before-queue", self.client.get(f"/api/download/{job_id}").get_data(as_text=True))

    def test_mismatched_platform_blocks_request_before_extraction(self):
        with patch.object(app, "extract_info_for_preview") as extract:
            response = self.client.post("/api/info", json={"url": DOUYIN, "cookie_platform": "xiaohongshu", "cookies_text": "key=value"})
            self.assertEqual(response.status_code, 400)
            self.assertIn("不一致", response.json["error"])
            extract.assert_not_called()

    def test_explicit_cookies_reach_preview_and_download_with_cleanup(self):
        for url in (DOUYIN, XHS, BILI):
            for download in (False, True):
                paths = []

                def extract(ydl, url, download):
                    return {"id": "fixture"}

                def factory(opts):
                    paths.append(Path(opts["cookiefile"]))
                    self.assertNotIn("Cookie", opts.get("http_headers", {}))
                    self.assertIn(app.cookie_domain_for_url(url), paths[-1].read_text())
                    from unittest.mock import MagicMock
                    return MagicMock()

                with patch.object(app.yt_dlp, "YoutubeDL", side_effect=factory), patch.object(app, "extract_platform_info", side_effect=extract):
                    app.extract_with_auto_cookies(url, download, cookie_text="key=dummy", use_browser_cookies=False)
                self.assertFalse(paths[0].exists())

    def test_error_categories(self):
        self.assertIn("新的 Cookie", app.readable_download_error(RuntimeError("Fresh cookies are needed"), DOUYIN))
        self.assertIn("访问限制", app.readable_download_error(RuntimeError("HTTP Error 403"), XHS))
        self.assertIn("xsec_token", app.readable_download_error(RuntimeError("Unable to extract initial state"), XHS))
        self.assertEqual(app.readable_download_error(RuntimeError("timed out"), BILI), "timed out")


class ExtractorTests(unittest.TestCase):
    def setUp(self):
        self.ydl = app.yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True})
        self.addCleanup(self.ydl.close)
        mock = patch.object(FetcherDouyinIE, "_signed_detail", return_value=None)
        mock.start()
        self.addCleanup(mock.stop)

    def test_share_redirects_keep_platform_and_xhs_token(self):
        for short, resolved, key in (("https://v.douyin.com/abc/", "https://www.iesdouyin.com/share/video/123456/", "FetcherDouyin"),
                                     ("http://xhslink.com/a/test", XHS, "FetcherXhs"),
                                     ("https://b23.tv/test", BILI, None)):
            extractor = FetcherShareIE(self.ydl)
            with patch.object(extractor, "_download_webpage_handle", return_value=("", SimpleNamespace(url=resolved))):
                result = extractor._real_extract(short)
                self.assertEqual(result["url"], app.normalize_supported_url(resolved))
                self.assertEqual(result.get("ie_key"), key)
        for resolved in ("https://evil.test/video/1", "https://v.douyin.com/still-short/", XHS):
            extractor = FetcherShareIE(self.ydl)
            with patch.object(extractor, "_download_webpage_handle", return_value=("", SimpleNamespace(url=resolved))):
                with self.assertRaises(ExtractorError):
                    extractor._real_extract("https://v.douyin.com/test/")

    def test_douyin_router_and_render_data_match_requested_video(self):
        video_id = "7491525659865720347"
        detail = {"aweme_id": video_id, "video": {"play_addr": {"url_list": ["https://media.example.test/video.mp4"]}}}
        for page in ("<script>window._ROUTER_DATA=" + json.dumps({"loaderData": {"aweme": detail}}) + ";</script>",
                     '<script id="RENDER_DATA" type="application/json">' + quote(json.dumps({"aweme": detail})) + "</script>"):
            extractor = FetcherDouyinIE(self.ydl)
            with patch.object(DouyinIE, "_real_extract", side_effect=ExtractorError("Fresh cookies needed")), \
                    patch.object(extractor, "_download_webpage", return_value=page), \
                    patch.object(extractor, "_parse_aweme_video_app", return_value={"id": video_id}) as parse:
                self.assertEqual(extractor._real_extract(DOUYIN)["id"], video_id)
                parse.assert_called_once_with(detail)
        self.assertIsNone(find_aweme({"recommended": {**detail, "aweme_id": "other"}}, video_id))

    def test_xhs_native_page_extracts_stream_and_duration(self):
        note_id = "674051740000000007027a15"
        state = {"note": {"noteDetailMap": {note_id: {"note": {
            "title": "小红书测试视频", "user": {"userId": "author"},
            "video": {"media": {"stream": {"h264": [{"masterUrl": "https://media.example.test/video.mp4",
                "duration": 12500, "width": 1920, "height": 1080, "videoCodec": "h264", "audioCodec": "aac"}]}}},
        }}}}}
        extractor = FetcherXhsIE(self.ydl)
        page = "<script>window.__INITIAL_STATE__=" + json.dumps(state, ensure_ascii=False) + ";</script>"
        with patch.object(extractor, "_download_webpage", return_value=page) as request:
            info = extractor._real_extract(XHS)
        self.assertEqual(request.call_args.args[0], XHS)
        self.assertEqual(info["title"], "小红书测试视频")
        self.assertEqual(info["duration"], 12.5)
        self.assertEqual(info["formats"][0]["height"], 1080)
        self.assertEqual(info["http_headers"]["Referer"], XHS)

    def test_xhs_image_note_reports_no_video(self):
        from yt_dlp.extractor.xiaohongshu import XiaoHongShuIE
        extractor = FetcherXhsIE(self.ydl)
        with patch.object(XiaoHongShuIE, "_real_extract", return_value={"formats": []}):
            with self.assertRaisesRegex(ExtractorError, "图文笔记"):
                extractor._real_extract(XHS)


if __name__ == "__main__":
    unittest.main()
