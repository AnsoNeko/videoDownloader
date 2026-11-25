import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


class YoutubeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = patch.object(app, "detect_js_runtimes", return_value={"node": {"path": "node"}})
        self.ejs = patch.object(app, "youtube_ejs_available", return_value=True)
        self.cookies = patch.object(app, "detect_cookie_file", return_value=None)
        for mocked in (self.runtime, self.ejs, self.cookies):
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_default_clients_and_runtime_for_preview_and_download(self):
        for download in (False, True):
            with patch.object(app.yt_dlp, "YoutubeDL") as factory:
                factory.return_value.__enter__.return_value.extract_info.return_value = {"id": "test"}
                app.extract_with_auto_cookies(URL, download, use_browser_cookies=False)
                opts = factory.call_args.args[0]
                self.assertEqual(opts["js_runtimes"], {"node": {"path": "node"}})
                self.assertNotIn("player_client", opts.get("extractor_args", {}).get("youtube", {}))

    def test_runtime_failure_does_not_block_other_platforms(self):
        with patch.object(app, "detect_js_runtimes", return_value={}):
            with self.assertRaisesRegex(RuntimeError, "Node.js"):
                app.apply_youtube_extractor_args({}, URL)
            self.assertEqual(app.apply_youtube_extractor_args({}, "https://x.com/a/status/1"), {})

    def test_missing_ejs_reports_fix(self):
        with patch.object(app, "youtube_ejs_available", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "update_dependencies"):
                app.apply_youtube_extractor_args({}, URL)

    def test_cookie_scope_and_temporary_file_cleanup_on_failure(self):
        text = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tdummy\n"
        paths = []

        def factory(opts):
            paths.append(Path(opts["cookiefile"]))
            self.assertEqual(paths[-1].read_text(encoding="utf-8"), text)
            self.assertNotIn("Cookie", opts.get("http_headers", {}))
            raise RuntimeError("network error")

        with patch.object(app.yt_dlp, "YoutubeDL", side_effect=factory):
            with self.assertRaisesRegex(RuntimeError, "network error"):
                app.extract_with_auto_cookies(URL, False, cookie_text=text)
        self.assertTrue(paths)
        self.assertFalse(paths[0].exists())

    def test_raw_cookie_header_becomes_domain_scoped_cookie_file(self):
        normalized = app.normalize_cookie_text("Cookie: SID=dummy; HSID=other", URL)
        self.assertEqual(normalized.count(".youtube.com\t"), 2)
        self.assertNotIn(".google.com", normalized)

    def test_public_video_does_not_read_browser_cookies(self):
        with patch.object(app.yt_dlp, "YoutubeDL") as factory:
            factory.return_value.__enter__.return_value.extract_info.return_value = {"id": "test"}
            app.extract_with_auto_cookies(URL, False, use_browser_cookies=True)
            self.assertEqual(factory.call_count, 1)
            self.assertNotIn("cookiesfrombrowser", factory.call_args.args[0])

    def test_network_error_does_not_trigger_browser_retry(self):
        with patch.object(app.yt_dlp, "YoutubeDL") as factory:
            factory.return_value.__enter__.return_value.extract_info.side_effect = RuntimeError("timed out")
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                app.extract_with_auto_cookies(URL, False)
            self.assertEqual(factory.call_count, 1)

    def test_auth_error_retries_browser_once_per_candidate(self):
        with patch.object(app, "detect_managed_browser_session", return_value=None):
            with patch.object(app.yt_dlp, "YoutubeDL") as factory:
                factory.return_value.__enter__.return_value.extract_info.side_effect = [
                    RuntimeError("Sign in to confirm you're not a bot"), {"id": "test"},
                ]
                self.assertEqual(app.extract_with_auto_cookies(URL, False), {"id": "test"})
                self.assertEqual(factory.call_count, 2)
                self.assertIn("cookiesfrombrowser", factory.call_args.args[0])

    def test_preview_failure_is_not_reported_as_success(self):
        with patch.object(app, "extract_with_auto_cookies", side_effect=RuntimeError("Sign in")):
            response = app.app.test_client().post("/api/info", json={"url": URL})
            self.assertEqual(response.status_code, 400)
            self.assertFalse(response.json["ok"])
            self.assertIn("cookies.txt", response.json["error"])

    def test_preview_includes_high_resolution_formats_after_first_18(self):
        formats = [
            {"format_id": f"audio-{index}", "ext": "m4a", "vcodec": "none", "acodec": "aac"}
            for index in range(18)
        ]
        formats.extend(
            {"format_id": format_id, "ext": "mp4", "vcodec": "av01", "acodec": "none", "height": height}
            for format_id, height in [("399", 1080), ("400", 1440), ("401", 2160)]
        )
        with patch.object(app, "extract_info_for_preview", return_value={"formats": formats}):
            response = app.app.test_client().post("/api/info", json={"url": URL, "use_saved_cookies": False})
        self.assertEqual(response.status_code, 200)
        format_ids = [item["format_id"] for item in response.json["info"]["formats"]]
        self.assertEqual(format_ids[-3:], ["399", "400", "401"])
        self.assertIn("audio-0", format_ids)

    def test_best_quality_and_no_ffmpeg_selection(self):
        with patch.object(app, "dependency_state", return_value={"ffmpeg_found": True}):
            self.assertEqual(app.build_download_format_candidates(URL, ""), ["bv*+ba/b"])
            self.assertEqual(app.build_download_format_candidates(URL, "137")[0], "137")
        with patch.object(app, "dependency_state", return_value={"ffmpeg_found": False}):
            self.assertEqual(app.build_download_format_candidates(URL, ""), ["b[ext=mp4]/b"])

    def test_merged_filename_is_used_for_completed_job(self):
        with tempfile.TemporaryDirectory() as folder:
            final = Path(folder) / "merged.mp4"
            final.write_bytes(b"video")

            def extract(url, download, extra_opts, **kwargs):
                extra_opts["post_hooks"][0](str(final))
                return {"_filename": str(Path(folder) / "old.webm"),
                        "requested_downloads": [{"filepath": str(Path(folder) / "old.f137.mp4")}]}

            with patch.object(app, "extract_with_auto_cookies", side_effect=extract):
                with patch.dict(app.DOWNLOAD_JOBS, {"test": {"id": "test"}}):
                    app.run_download_job("test", URL, "", False, "")
                    self.assertEqual(app.get_job("test")["status"], "completed")
                    self.assertEqual(app.get_job("test")["file_name"], "merged.mp4")

    def test_missing_output_is_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                app.resolve_downloaded_path({"filepath": str(Path(folder) / "missing.mp4")})

    def test_missing_yt_dlp_is_json_error(self):
        with patch.object(app, "yt_dlp", None):
            for endpoint in ("/api/info", "/api/download"):
                response = app.app.test_client().post(endpoint, json={"url": URL})
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json["ok"])


if __name__ == "__main__":
    unittest.main()
