import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from platform_support import detect_cookie_platform


def netscape(domain, name="sessionid"):
    return f"# Netscape HTTP Cookie File\n{domain}\tTRUE\t/\tTRUE\t0\t{name}\tdummy\n"


class CookieDetectionTests(unittest.TestCase):
    def test_nameless_raw_entries_do_not_reject_other_session_cookies(self):
        text = "hevc_supported=true; ttwid=dummy; =orphan; sessionid=valid-session; token=a=b==; empty=; ="
        normalized = app.normalize_cookie_text(text, "https://www.douyin.com/video/123")
        rows = [line.split("\t") for line in normalized.splitlines() if not line.startswith("#")]
        self.assertEqual({row[5]: row[6] for row in rows}, {
            "hevc_supported": "true", "ttwid": "dummy", "sessionid": "valid-session",
            "token": "a=b==", "empty": "",
        })
        with self.assertRaises(ValueError):
            app.normalize_cookie_text("=orphan; =", "https://www.douyin.com/video/123")
        with self.assertRaisesRegex(ValueError, "名称不正确"):
            app.normalize_cookie_text("ttwid=dummy; bad name=value", "https://www.douyin.com/video/123")

    def test_nameless_netscape_rows_and_trailing_empty_value(self):
        text = ("# Netscape HTTP Cookie File\n"
                ".douyin.com\tTRUE\t/\tTRUE\t0\t\torphan\n"
                ".douyin.com\tTRUE\t/\tTRUE\t0\tttwid\tdummy\n"
                ".douyin.com\tTRUE\t/\tTRUE\t0\tempty\t")
        normalized = app.normalize_cookie_text(text, "https://www.douyin.com/video/123")
        self.assertNotIn("orphan", normalized)
        self.assertTrue(normalized.endswith("\tempty\t\n"))
        self.assertEqual(app.normalize_cookie_text(normalized, "https://www.douyin.com/video/123"), normalized)
        self.assertEqual(detect_cookie_platform(".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\t")["platform"], "bilibili")

    def test_save_detect_and_preview_accept_nameless_entry(self):
        text = "ttwid=dummy; =orphan; sessionid=valid-session"
        with tempfile.TemporaryDirectory() as folder, patch.object(app, "AUTH_DIR", Path(folder)):
            client = app.app.test_client()
            response = client.post("/api/cookies", json={"cookies_text": text})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["platform"], "douyin")
            with patch.object(app, "extract_info_for_preview", return_value={"formats": []}) as extract:
                response = client.post("/api/info", json={"url": "https://www.douyin.com/video/123", "cookies_text": text})
                self.assertEqual(response.status_code, 200)
                used = extract.call_args.args[2]
                self.assertIn("\tsessionid\tvalid-session", used)
                self.assertNotIn("orphan", used)

    def test_domain_and_httponly_detection(self):
        for platform, domain in (("douyin", ".douyin.com"), ("xiaohongshu", ".xiaohongshu.com"),
                                 ("bilibili", ".bilibili.com"), ("youtube", ".youtube.com"),
                                 ("x", ".twitter.com"), ("instagram", ".instagram.com")):
            with self.subTest(platform=platform):
                result = detect_cookie_platform(netscape(domain))
                self.assertEqual(result["platform"], platform)
                self.assertEqual(result["source"], "domain")
                self.assertEqual(detect_cookie_platform(netscape("#HttpOnly_" + domain))["platform"], platform)

    def test_raw_cookie_detection_without_video_link(self):
        for platform, cookie in (("douyin", "sessionid=dummy; ttwid=other"),
                                 ("xiaohongshu", "web_session=dummy; a1=other"),
                                 ("xiaohongshu", "a1=dummy; webId=other"),
                                 ("bilibili", "SESSDATA=dummy; bili_jct=other"),
                                 ("youtube", "LOGIN_INFO=dummy; YSC=other"),
                                 ("x", "auth_token=dummy; ct0=other"),
                                 ("instagram", "sessionid=dummy; ds_user_id=123")):
            for prefix in ("", "Cookie: "):
                with self.subTest(platform=platform, prefix=prefix):
                    self.assertEqual(detect_cookie_platform(prefix + cookie)["platform"], platform)

    def test_generic_names_values_and_foreign_domains_cannot_choose_platform(self):
        for text in ("sessionid=dummy; token=other; csrftoken=abc", "a1=dummy", "key=SESSDATA",
                     netscape(".bilibili.com.evil.test"), netscape(".tiktok.com", "ttwid")):
            self.assertIsNone(detect_cookie_platform(text)["platform"])
        self.assertEqual(detect_cookie_platform("sessionid=dummy", "https://www.douyin.com/video/123")["platform"], "douyin")

    def test_authoritative_cookie_platform_wins_over_unrelated_url(self):
        for text in (netscape(".xiaohongshu.com"), "web_session=dummy"):
            self.assertEqual(detect_cookie_platform(text, "https://www.youtube.com/watch?v=test")["platform"], "xiaohongshu")
        self.assertEqual(detect_cookie_platform(netscape(".bilibili.com", "web_session"))["platform"], "bilibili")

    def test_combined_files_require_selection_or_matching_link(self):
        text = netscape(".douyin.com") + netscape(".xiaohongshu.com")
        result = detect_cookie_platform(text)
        self.assertIsNone(result["platform"])
        self.assertEqual(result["source"], "ambiguous")
        self.assertCountEqual(result["candidates"], ["douyin", "xiaohongshu"])
        self.assertEqual(detect_cookie_platform(text, "http://xhslink.com/a/test")["platform"], "xiaohongshu")
        self.assertIsNone(detect_cookie_platform(text, "https://b23.tv/test")["platform"])

    def test_detect_and_save_api_first_use_and_wrong_previous_selection(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app, "AUTH_DIR", Path(folder)):
            client = app.app.test_client()
            for platform, text in (("bilibili", "SESSDATA=private-fixture"),
                                   ("douyin", "ttwid=private-fixture"),
                                   ("xiaohongshu", netscape(".xiaohongshu.com"))):
                detected = client.post("/api/cookies/detect", json={"cookies_text": text})
                self.assertEqual(detected.json["platform"], platform)
                for previous in ("", "youtube"):
                    response = client.post("/api/cookies", json={"platform": previous, "cookies_text": text})
                    self.assertEqual(response.status_code, 200, response.json)
                    self.assertEqual(response.json["platform"], platform)
                    self.assertTrue(app.platform_cookie_path(platform).is_file())
                    self.assertNotIn("private-fixture", response.get_data(as_text=True))
                self.assertNotIn("private-fixture", detected.get_data(as_text=True))
            self.assertFalse(app.platform_cookie_path("youtube").exists())

    def test_unknown_and_ambiguous_api_do_not_save_to_default(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app, "AUTH_DIR", Path(folder)):
            client = app.app.test_client()
            for text in ("sessionid=dummy", netscape(".douyin.com") + netscape(".xiaohongshu.com")):
                response = client.post("/api/cookies", json={"cookies_text": text})
                self.assertEqual(response.status_code, 400)
                self.assertIn("无法唯一识别", response.json["error"])
            self.assertFalse(any(app.saved_cookie_state().values()))
            response = client.post("/api/cookies", json={"cookies_text": "sessionid=dummy", "url": "https://v.douyin.com/test/"})
            self.assertEqual(response.json["platform"], "douyin")
            response = client.post("/api/cookies", json={"cookies_text": "sessionid=dummy", "platform": "xiaohongshu", "url": "https://v.douyin.com/test/"})
            self.assertEqual(response.json["platform"], "xiaohongshu")

    def test_raw_cookies_for_wrong_platform_are_rejected_even_if_ui_platform_matches_link(self):
        client = app.app.test_client()
        with patch.object(app, "extract_info_for_preview") as extract:
            response = client.post("/api/info", json={"url": "https://www.douyin.com/video/123", "cookie_platform": "douyin", "cookies_text": "web_session=dummy"})
            self.assertEqual(response.status_code, 400)
            self.assertIn("不一致", response.json["error"])
            extract.assert_not_called()


if __name__ == "__main__":
    unittest.main()
