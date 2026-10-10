import errno
import json
import socket
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch
from urllib.error import URLError

from tools.wubu_tool.autostart import WubuAutoStarter, connection_refused
from tools.wubu_tool.client import WubuClient, WubuError
from tools.wubu_tool.package import create_package


def refused_error():
    error = WubuError("wubu_unavailable", "refused", retryable=True)
    error.refused = True
    return error


class AutoStartTests(unittest.TestCase):
    def test_refusal_detection(self):
        self.assertTrue(connection_refused(URLError(ConnectionRefusedError(errno.ECONNREFUSED, "refused"))))
        self.assertTrue(connection_refused(OSError(10061, "refused")))
        for error in [TimeoutError(), ConnectionResetError(), URLError("connection refused"), OSError(11001, "DNS")]:
            self.assertFalse(connection_refused(error))

    def test_refused_connect_starts_and_resumes_real_http(self):
        reserved = socket.socket()
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        reserved.close()
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.reply({"status": "ok", "database": "ok"})

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append((self.path, payload, self.headers.get("Idempotency-Key")))
                self.reply({"recorded": True})

            def reply(self, data):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())

        started = []

        def launch():
            reserved.close()
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            started.append((server, thread))
            return Mock(poll=Mock(return_value=None))

        client = WubuClient(f"http://127.0.0.1:{port}", timeout=5)
        client.starter = WubuAutoStarter(client.base_url, timeout=5)
        try:
            with patch.object(client.starter, "_launch", side_effect=launch) as launcher:
                result = client.request("POST", "/api/v1/purchases", payload={"total_amount": 22}, key="original-key")
                self.assertEqual(result[0], {"recorded": True})
                launcher.assert_called_once()
                self.assertEqual(calls, [("/api/v1/purchases", {"total_amount": 22}, "original-key")])
        finally:
            reserved.close()
            for server, thread in started:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_no_start_on_timeout_reset_http_or_bad_json(self):
        client = WubuClient(autostart=True)
        with patch.object(client.starter, "ensure_ready") as starter:
            for error in [TimeoutError(), ConnectionResetError(), OSError(11001, "DNS")]:
                with patch("tools.wubu_tool.client.build_opener") as opener:
                    opener.return_value.open.side_effect = error
                    with self.assertRaises(WubuError) as caught:
                        client.request("POST", "/api/v1/purchases", payload={}, key="same-key")
                    self.assertTrue(caught.exception.unknown)
            for error in [WubuError("http_503", "server", unknown=True), WubuError("invalid_response", "invalid", unknown=True)]:
                with patch.object(client, "_request_once", side_effect=error), self.assertRaises(WubuError):
                    client.request("POST", "/api/v1/purchases", payload={}, key="same-key")
            starter.assert_not_called()

    def test_only_one_resume_and_same_arguments(self):
        client = WubuClient(autostart=True)
        with patch.object(client, "_request_once", side_effect=[refused_error(), refused_error()]) as request:
            with patch.object(client.starter, "ensure_ready") as starter, self.assertRaises(WubuError) as caught:
                client.request("POST", "/write", {"q": 1}, {"amount": 22}, "original-key")
            starter.assert_called_once()
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args_list[0], request.call_args_list[1])
            self.assertFalse(caught.exception.unknown)

    def test_launch_failure_and_timeout_are_not_unknown_writes(self):
        client = WubuClient(autostart=True, project_dir="missing-wubu-project", startup_timeout=0.04)
        with patch.object(client, "_request_once", side_effect=refused_error()):
            with patch.object(client.starter, "_probe", side_effect=refused_error()):
                with patch.object(client.starter, "_launch", side_effect=OSError("missing script")):
                    with self.assertRaises(WubuError) as caught:
                        client.request("POST", "/write", payload={}, key="k")
                    self.assertEqual(caught.exception.code, "wubu_start_failed")
                    self.assertFalse(caught.exception.unknown)
                with patch.object(client.starter, "_launch", return_value=Mock(poll=Mock(return_value=0))):
                    with self.assertRaises(WubuError) as caught:
                        client.request("POST", "/write", payload={}, key="k")
                    self.assertEqual(caught.exception.code, "wubu_start_timeout")
                    self.assertFalse(caught.exception.unknown)

    def test_concurrent_instances_launch_once(self):
        starters = [WubuAutoStarter("http://127.0.0.1:8026", project_dir="concurrency-test") for _ in range(4)]
        ready = threading.Event()
        process = Mock(poll=Mock(return_value=None))

        def probe(*args, **kwargs):
            if not ready.is_set():
                raise refused_error()

        def launch(*args):
            ready.set()
            return process

        with patch.object(WubuAutoStarter, "_probe", side_effect=probe):
            with patch.object(WubuAutoStarter, "_launch", side_effect=launch) as launcher:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    list(pool.map(lambda starter: starter.ensure_ready(), starters))
                launcher.assert_called_once()

    def test_health_probe_does_not_start_and_package_defaults(self):
        package = create_package()
        package.configure({})
        self.assertIsNotNone(package.client.starter)
        self.assertEqual(package.client.starter.project_dir.name, "物簿")
        package.configure({"base_url": "http://127.0.0.1:9999", "autostart_enabled": "false"})
        self.assertIsNone(package.client.starter)
        with patch.object(WubuAutoStarter, "_launch") as launch:
            with patch.object(WubuClient, "_request_once", side_effect=refused_error()):
                self.assertFalse(package.health_check({})["healthy"])
            launch.assert_not_called()

    def test_launcher_uses_hidden_documented_script(self):
        starter = WubuAutoStarter("http://127.0.0.1:8026")
        with patch("tools.wubu_tool.autostart.Path.is_file", return_value=True):
            with patch("tools.wubu_tool.autostart.subprocess.Popen") as launch:
                starter._launch()
                args, kwargs = launch.call_args
                self.assertEqual(args[0][0], "powershell.exe")
                self.assertEqual(args[0][-1], str(starter.project_dir / "scripts" / "start.ps1"))
                self.assertEqual(kwargs["cwd"], str(starter.project_dir))
                self.assertTrue(kwargs["creationflags"])
