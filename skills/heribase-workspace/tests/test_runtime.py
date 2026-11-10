import concurrent.futures
import json
import select
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from workspace_runtime import start_workspace, stop_workspace, read_runtime, request_workspace


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        stop_workspace(self.home)
        self.tmp.cleanup()

    def test_concurrent_start_reuses_one_service_and_restart_keeps_data(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            starts = list(pool.map(lambda _: start_workspace(self.home, open_browser=False), range(2)))
        self.assertEqual(starts[0]["url"], starts[1]["url"])
        first = read_runtime(self.home)
        request_workspace(self.home, "/api/entities", {"kind": "note", "id": "coin-one", "expectedRevision": 0, "data": {"text": "持久化"}}, role="browser")
        stop_workspace(self.home)
        self.assertIsNone(read_runtime(self.home))
        start_workspace(self.home, open_browser=False)
        second = read_runtime(self.home)
        self.assertNotEqual(first["instanceId"], second["instanceId"])
        snapshot = request_workspace(self.home, "/api/snapshot")
        self.assertEqual(snapshot["notes"][0]["data"]["text"], "持久化")

    def test_stale_metadata_is_not_mistaken_for_a_running_service(self):
        directory = self.home / ".heribase" / "workspace"
        directory.mkdir(parents=True)
        (directory / "runtime.json").write_text(json.dumps({"url": "http://127.0.0.1:1", "protocolVersion": 1, "instanceId": "dead", "browserKey": "b", "hostKey": "h"}))
        result = start_workspace(self.home, open_browser=False, page="review", task_key="20260923-0000-sample")
        self.assertIn("page=review", result["url"])
        self.assertIn("task=20260923-0000-sample", result["url"])
        self.assertEqual((directory / "runtime.json").stat().st_mode & 0o777, 0o600)

    def test_add_page_can_resume_the_same_local_task_without_opening_a_browser(self):
        from urllib.request import urlopen
        started = start_workspace(self.home, open_browser=False, page="add")
        self.assertFalse(started["opened"])
        self.assertIn("page=add", started["url"])
        runtime = read_runtime(self.home)
        with urlopen(runtime["url"] + "/add.js", timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get("Cache-Control"), "no-store")
            self.assertIn(b"export", response.read())
        again = start_workspace(self.home, open_browser=False, page="add")
        self.assertTrue(again["reused"])
        self.assertEqual(started["url"], again["url"])

    def test_foreground_serve_prints_its_listening_address_without_credentials(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "workspace.py"
        process = subprocess.Popen(
            [sys.executable, str(script), "serve", "--home", str(self.home), "--port", "0"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            readable, _, _ = select.select([process.stdout], [], [], 5)
            self.assertTrue(readable, "serve should announce its listening address promptly")
            announcement = json.loads(process.stdout.readline())
            self.assertTrue(announcement["ok"])
            self.assertEqual(announcement["status"], "serving")
            self.assertRegex(announcement["url"], r"^http://127\.0\.0\.1:[0-9]+$")
            self.assertNotIn("access=", json.dumps(announcement))
        finally:
            process.terminate()
            process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()

    def test_host_transport_preserves_explicit_pre_write_failure_details(self):
        from io import BytesIO
        from unittest.mock import patch
        from urllib.error import HTTPError
        from workspace_runtime import http_json
        from workspace_store import WorkspaceError
        payload = {"error": {"code": "cli_invalid_output", "message": "只读查询失败", "remoteWriteStarted": False}}
        error = HTTPError("http://127.0.0.1:1/api/connector/identify", 502, "query failed", {}, BytesIO(json.dumps(payload).encode()))
        with patch("workspace_runtime.build_opener") as factory:
            factory.return_value.open.side_effect = error
            with self.assertRaises(WorkspaceError) as raised:
                http_json(error.url, "synthetic-test-key", {})
        self.assertIs(raised.exception.details["remoteWriteStarted"], False)
        self.assertEqual(raised.exception.status, 502)


if __name__ == "__main__":
    unittest.main()
