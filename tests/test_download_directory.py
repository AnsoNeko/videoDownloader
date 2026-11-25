import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
EXTENSION_URL = "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc"


class DownloadDirectoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.default = self.root / "default"
        self.default.mkdir()
        for name, value in (("SETTINGS_PATH", self.root / "settings.json"),
                            ("RUNTIME_DIR", self.root), ("DOWNLOADS_DIR", self.default)):
            mocked = patch.object(app, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.client = app.app.test_client()

    def test_save_create_reload_and_restore_default(self):
        directory = self.root / "中文 路径" / "视频"
        response = self.client.post("/api/settings", json={"download_dir": str(directory)})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(directory.is_dir())
        self.assertEqual(app.get_download_directory(), directory)
        self.assertEqual(self.client.get("/api/state").json["download_dir"], str(directory))
        self.assertEqual(self.client.post("/api/settings", json={"download_dir": ""}).json["download_dir"], str(self.default))

    def test_invalid_path_does_not_replace_saved_directory(self):
        app.save_download_directory(self.default)
        for value in ("relative/path", 123, None):
            response = self.client.post("/api/settings", json={"download_dir": value})
            self.assertEqual(response.status_code, 400)
        file = self.root / "file.txt"
        file.write_text("test")
        self.assertEqual(self.client.post("/api/settings", json={"download_dir": str(file)}).status_code, 400)
        with patch.object(app.tempfile, "TemporaryFile", side_effect=PermissionError("access denied")):
            self.assertEqual(self.client.post("/api/settings", json={"download_dir": str(self.root)}).status_code, 400)
        with patch.object(app.Path, "expanduser", side_effect=RuntimeError("unknown user")):
            self.assertEqual(self.client.post("/api/settings", json={"download_dir": "~unknown"}).status_code, 400)
        self.assertEqual(app.get_download_directory(), self.default)

    def test_corrupt_settings_fall_back(self):
        for content in ("not json", "[]", '{"download_dir": 42}', '{"download_dir": "relative"}'):
            app.SETTINGS_PATH.write_text(content)
            self.assertEqual(app.get_download_directory(), self.default)

    def test_queued_jobs_keep_their_own_directories(self):
        directories = [self.root / "first", self.root / "second"]
        with patch.object(app.threading, "Thread") as worker:
            responses = [self.client.post("/api/download", json={"url": URL, "download_dir": str(directory)})
                         for directory in directories]
            for response, directory, call in zip(responses, directories, worker.call_args_list):
                self.assertEqual(response.status_code, 200)
                job_id = response.json["job_id"]
                self.addCleanup(app.DOWNLOAD_JOBS.pop, job_id, None)
                self.assertEqual(app.get_job(job_id)["download_dir"], str(directory))
                self.assertEqual(call.kwargs["args"][-1], directory)

    def test_invalid_download_directory_does_not_start_worker(self):
        with patch.object(app.threading, "Thread") as worker:
            response = self.client.post("/api/download", json={"url": URL, "download_dir": "relative"})
            self.assertEqual(response.status_code, 400)
            worker.assert_not_called()

    def test_existing_clients_use_saved_directory(self):
        directory = self.root / "saved"
        directory.mkdir()
        app.save_download_directory(directory)
        with patch.object(app.threading, "Thread") as worker:
            response = self.client.post("/api/download", json={"url": URL})
            self.assertEqual(response.status_code, 200)
            self.addCleanup(app.DOWNLOAD_JOBS.pop, response.json["job_id"], None)
            self.assertEqual(worker.call_args.kwargs["args"][-1], directory)

    def test_download_uses_snapshot_and_escapes_template_percent(self):
        directory = self.root / "100% 视频"
        directory.mkdir()
        final = directory / "video.mp4"
        final.write_bytes(b"media")

        def extract(url, download, extra_opts, **kwargs):
            self.assertTrue(extra_opts["outtmpl"].startswith(str(directory).replace("%", "%%")))
            app.save_download_directory(self.default)
            extra_opts["post_hooks"][0](str(final))
            return {"filepath": str(final)}

        with patch.dict(app.DOWNLOAD_JOBS, {"path-test": {"id": "path-test"}}):
            with patch.object(app, "extract_with_auto_cookies", side_effect=extract):
                app.run_download_job("path-test", URL, "", False, "", directory)
            self.assertEqual(app.get_job("path-test")["status"], "completed")
            self.assertEqual(app.get_job("path-test")["download_dir"], str(directory))

    def test_picker_cancel_preserves_settings(self):
        with patch.object(app, "choose_download_directory", return_value=None):
            response = self.client.post("/api/download-directory/choose", json={})
        self.assertTrue(response.json["cancelled"])
        self.assertEqual(app.get_download_directory(), self.default)

    def test_page_has_saved_path_and_extension_button(self):
        app.save_download_directory(self.default)
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn(str(self.default), html)
        self.assertIn(f'href="{EXTENSION_URL}"', html)
        self.assertIn('rel="noopener noreferrer"', html)


if __name__ == "__main__":
    unittest.main()
