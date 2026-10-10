import asyncio
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import urlsplit

from pydantic import ValidationError
from zhaoxi.sdk import PermissionLevel, SideEffect
from tools.wubu_tool.client import WubuClient, WubuError
from tools.wubu_tool.package import create_package
from tools.wubu_tool.tool import CONTRACT, PURCHASE_ID_OPERATIONS, WubuInput, WubuTool, read_only_operation, path_id_field


class Handler(BaseHTTPRequestHandler):
    calls = []
    events = {}

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.handle_call()

    def do_POST(self):
        self.handle_call()

    def do_PATCH(self):
        self.handle_call()

    def do_PUT(self):
        self.handle_call()

    def do_DELETE(self):
        self.handle_call()

    def handle_call(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        data = json.loads(raw) if raw else None
        key = self.headers.get("Idempotency-Key")
        self.calls.append((self.command, self.path, data, key))
        status, replayed = 200, False
        response = {"method": self.command, "path": self.path, "payload": data}
        if self.path == "/healthz":
            response = {"status": "ok", "database": "ok"}
        elif "/unavailable" in self.path:
            status, response = 503, {"error": {"code": "unavailable", "message": "数据库不可用"}}
        elif "/invalid" in self.path:
            response = None
        elif self.path.endswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "/redirect-target")
            self.end_headers()
            return
        elif key:
            fingerprint = (self.command, self.path, raw)
            if key in self.events:
                if self.events[key][0] == fingerprint:
                    replayed, response = True, self.events[key][1]
                else:
                    status, response = 409, {"error": {"code": "idempotency_conflict", "message": "参数改变"}}
            else:
                self.events[key] = (fingerprint, response)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if replayed:
            self.send_header("Idempotency-Replayed", "true")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode() if response is not None else b"broken JSON")


class WubuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        Handler.calls.clear()
        Handler.events.clear()
        self.tool = WubuTool(WubuClient(self.url, 1))

    def run_tool(self, **arguments):
        return asyncio.run(self.tool.run(arguments))

    def test_every_route_and_permission(self):
        examples = {"record_purchase_event": {"total_amount": 1, "items": []},
                    "consume_item": {"quantity": 1}, "adjust_inventory": {"quantity": 5},
                    "add_maintenance_event": {"title": "换胎", "cost": 65},
                    "add_product_alias": {"alias": "零度可乐"}}
        examples.update({"record_purchase": {"items": [{"name": "可乐", "quantity": 1, "unit": "瓶"}]},
                         "validate_purchase": {"items": [{"name": "可乐", "quantity": 1, "unit": "瓶"}]},
                         "amend_purchase_event": {"total_amount": 1, "items": [], "expected_updated_at": "2026-10-06T01:00:00Z",
                                                  "source": "agent", "external_id": ""},
                         "delete_purchase_event": {"expected_updated_at": "2026-10-06T01:00:00Z"}})
        examples.update({f"{action}_by_name": {"name": "可乐", **({"quantity": 1} if action in {"consume", "adjust"} else {})}
                         for action in ["consume", "adjust", "open", "finish", "discard"]})
        for operation, spec in CONTRACT.items():
            with self.subTest(operation=operation):
                args = {"operation": operation}
                if "{id}" in spec["path"]:
                    args[path_id_field(operation)] = "test-item"
                if spec["method"] != "GET":
                    args["payload"] = examples.get(operation, {
                        key: (["sample"] if field.get("type") == "array" else
                              1 if field.get("type") in {"number", "integer"} else
                              field.get("enum", ["sample"])[0])
                        for key,field in spec["payload"].get("properties", {}).items()
                        if key in spec["payload"].get("required", [])})
                    if operation != "validate_purchase":
                        args["idempotency_key"] = operation
                if operation == "resolve_item":
                    args["query"] = {"name": "零度可乐"}
                result = asyncio.run(self.tool.run(args))
                self.assertTrue(result.success, result)
                self.assertEqual(Handler.calls[-1][0], spec["method"])
                self.assertEqual(urlsplit(Handler.calls[-1][1]).path, spec["path"].replace("{id}", "test-item"))
                write = not read_only_operation(args)
                self.assertEqual(self.tool.permission_for(args), PermissionLevel.WRITE if write else PermissionLevel.READ)
                self.assertEqual(self.tool.side_effects_for(args), frozenset({SideEffect.LOCAL_STATE if write else SideEffect.NONE}))
                self.assertTrue(self.tool.safe_to_replay(args))
        self.assertTrue(self.tool.default_confirm_write)

    def test_idempotency_and_conflict(self):
        args = dict(operation="consume_item", item_id="cola", idempotency_key="event-001", payload={"quantity": 1})
        first = self.run_tool(**args)
        second = self.run_tool(**args)
        self.assertEqual(first.data, second.data)
        self.assertTrue(second.metadata["idempotency_replayed"])
        self.assertEqual(len(Handler.events), 1)
        args["payload"] = {"quantity": 2}
        conflict = self.run_tool(**args)
        self.assertEqual(conflict.error, "idempotency_conflict")
        self.assertFalse(conflict.metadata["unknown_outcome"])
        self.assertFalse(conflict.metadata["retryable"])
        self.assertEqual(len(Handler.calls), 3)

    def test_validation_before_network(self):
        invalid = [dict(operation="invented"), dict(operation="get_item"),
                   dict(operation="consume_item", item_id="x", payload={"quantity": 1}),
                   dict(operation="consume_item", item_id="x", idempotency_key="key"),
                   dict(operation="resolve_item"), dict(operation="get_inventory", query={"typo": 1}),
                   dict(operation="get_item", item_id=".."),
                   dict(operation="get_inventory", query={"search": float("nan")}),
                   dict(operation="consume_item", item_id="x", idempotency_key="bad\nkey", payload={"quantity": 1})]
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(ValidationError):
                WubuInput.model_validate(args)
        self.assertEqual(Handler.calls, [])

    def test_query_and_encoded_id(self):
        result = self.run_tool(operation="get_inventory", query={"search": "可乐 & 泡面", "hide_out": True})
        self.assertTrue(result.success)
        self.assertIn("hide_out=true", Handler.calls[-1][1])
        self.run_tool(operation="get_item", item_id="x/y?z")
        self.assertEqual(Handler.calls[-1][1], "/api/v1/items/x%2Fy%3Fz")
        self.run_tool(operation="get_inventory_history", item_id="cola")
        self.assertEqual(Handler.calls[-1][1], "/api/v1/items/cola/inventory-events")

    def test_uncertain_errors_and_no_retry(self):
        for identifier, code in [("unavailable", "unavailable"), ("invalid", "invalid_response")]:
            write = self.run_tool(operation="update_durable_details", item_id=identifier, idempotency_key="k", payload={})
            self.assertFalse(write.success)
            self.assertEqual(write.error, code)
            self.assertTrue(write.metadata["unknown_outcome"])
            read = self.run_tool(operation="get_item", item_id=identifier)
            self.assertFalse(read.metadata["unknown_outcome"])
        self.assertEqual(len(Handler.calls), 4)
        with patch.object(self.tool.client, "request", side_effect=WubuError("wubu_unavailable", "timeout", unknown=True, retryable=True)) as request:
            result = self.run_tool(operation="consume_item", item_id="x", idempotency_key="k", payload={"quantity": 1})
            self.assertTrue(result.metadata["unknown_outcome"])
            request.assert_called_once()

    def test_local_url_and_redirect(self):
        for url in ["https://127.0.0.1", "http://example.com", "http://127.0.0.1/api", "http://user@localhost", "http://localhost?x=1"]:
            with self.assertRaises(ValueError):
                WubuClient(url)
        for timeout in [0, -1, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                WubuClient(timeout=timeout)
        result = self.run_tool(operation="get_item", item_id="redirect")
        self.assertFalse(result.success)
        self.assertEqual(len(Handler.calls), 1)

    def test_transport_timeout_preserves_key(self):
        with patch("tools.wubu_tool.client.build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError("timeout")
            result = self.run_tool(operation="consume_item", item_id="cola", idempotency_key="original-key",
                                   payload={"quantity": 1})
            self.assertEqual(result.error, "wubu_unavailable")
            self.assertTrue(result.metadata["unknown_outcome"])
            opener.return_value.open.assert_called_once()
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header("Idempotency-key"), "original-key")
        with patch("tools.wubu_tool.client.build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError("timeout")
            result = self.run_tool(operation="get_item", item_id="cola")
            self.assertFalse(result.metadata["unknown_outcome"])

    def test_package_and_schema(self):
        package = create_package()
        self.assertEqual(package.requires_sdk, ">=1,<2")
        self.assertEqual(package.capability_declaration().enabled_names(), ["tool"])
        self.assertEqual([t.name for t in package.create_tools({"base_url": self.url, "autostart_enabled": False})][:4],
                         ["record_purchase", "validate_purchase", "wubu_inventory_event", "wubu"])
        self.assertTrue(package.health_check({"base_url": self.url})["healthy"])
        schema = self.tool.schema()["function"]["parameters"]
        self.assertEqual({s["properties"]["operation"]["const"] for s in schema["oneOf"]}, set(CONTRACT))
        purchase = next(s for s in schema["oneOf"] if s["properties"]["operation"]["const"] == "record_purchase_event")
        self.assertIn("items", purchase["properties"]["payload"]["required"])
        self.assertIn("unit_price", purchase["properties"]["payload"]["properties"]["items"]["items"]["properties"])
        self.assertNotIn("$ref", json.dumps(schema))


if __name__ == "__main__":
    unittest.main()
