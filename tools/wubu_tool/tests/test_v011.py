"""SDK/adapter regressions against a scripted HTTP double, not Wubu's database."""
import asyncio
from copy import deepcopy
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from zhaoxi.sdk import PermissionLevel, SideEffect
from zhaoxi.tools.packages import discover_tool_packages
from tools.wubu_tool.client import WubuClient
from tools.wubu_tool.high_level import RecordPurchaseTool, ValidatePurchaseTool, InventoryEventTool
from tools.wubu_tool.sync_schema import OPERATIONS
from tools.wubu_tool.tool import CONTRACT, WubuTool


def summary(name="无糖可乐", spec="2L", added=1, after=1, item_id="cola-2l", amount=5.5):
    return {"purchase_id": "purchase-1", "expense_amount": amount, "validation_status": "VALID", "warnings": [],
            "items": [{"item_id": item_id, "name": name, "spec": spec, "quantity_added": added,
                       "unit": "瓶", "inventory_after": after}]}


def error(code, message, **extra):
    return {"validation_status": "ERROR", "request_id": "request-1",
            "error": {"code": code, "message": message, "retryable": False,
                      "suggested_action": "clarify_item", **extra}}


class ScriptedHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.reply()

    def do_POST(self):
        self.reply()

    def do_PUT(self):
        self.reply()

    def do_DELETE(self):
        self.reply()

    def reply(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        payload = json.loads(raw) if raw else None
        key = self.headers.get("Idempotency-Key")
        self.server.calls.append({"method": self.command, "path": self.path, "payload": payload, "key": key})
        fingerprint = (self.command, self.path, raw)
        replayed = False
        if key in self.server.committed:
            old_fingerprint, data = self.server.committed[key]
            if fingerprint != old_fingerprint:
                status, data = 409, error("IDEMPOTENCY_CONFLICT", "same key different parameters")
            else:
                status, replayed = 200, True
        else:
            queue = self.server.responses.get((self.command, self.path), [])
            if not queue:
                status, data = 500, error("UNEXPECTED_REQUEST", "adapter made an unplanned request")
            else:
                status, data = queue.pop(0)
            if key and status < 400:
                self.server.committed[key] = (fingerprint, deepcopy(data))
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if replayed:
            self.send_header("Idempotency-Replayed", "true")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())


class V011Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.server.calls, self.server.committed, self.server.responses = [], {}, {}
        client = WubuClient(self.url, 1)
        self.record = RecordPurchaseTool(client)
        self.validate = ValidatePurchaseTool(client)
        self.inventory = InventoryEventTool(client)
        self.advanced = WubuTool(client)

    def plan(self, method, path, *responses):
        self.server.responses[(method, path)] = [(200, deepcopy(r)) if not isinstance(r, tuple) else r for r in responses]

    def invoke(self, tool, arguments):
        return asyncio.run(tool.run(arguments))

    def purchase_args(self, *, key="purchase-key", **line):
        return {"items": [{"name": "无糖可乐", "spec": "2L", "quantity": 1, "unit": "瓶", "price": 5.5, **line}],
                "idempotency_key": key}

    def test_2l_bottle_purchase_and_direct_confirmation(self):
        self.plan("POST", "/api/v1/purchases/record", summary())
        result = self.invoke(self.record, self.purchase_args())
        self.assertTrue(result.success, result)
        self.assertEqual(len(self.server.calls), 1)
        sent = self.server.calls[0]
        self.assertEqual(sent["key"], "purchase-key")
        self.assertEqual(sent["payload"]["items"][0], {"name": "无糖可乐", "spec": "2L", "quantity": 1.0, "unit": "瓶", "price": 5.5})
        for field in ["operation", "payload", "source", "currency", "purchased_at", "idempotency_key"]:
            self.assertNotIn(field, sent["payload"])
        for text in ["无糖可乐 2L", "1瓶", "¥5.50", "当前库存 1瓶", "purchase-1", "VALID"]:
            self.assertIn(text, result.content)
        self.assertEqual(result.data, summary())

    def test_first_tea_and_repeat_same_item_1_to_3(self):
        self.plan("POST", "/api/v1/purchases/record",
                  summary(name="东方树叶", spec="900ml", item_id="tea-900", amount=5), summary(),
                  summary(added=2, after=3, amount=11))
        tea = self.invoke(self.record, self.purchase_args(key="tea", name="东方树叶", spec="900ml", price=5))
        self.assertTrue(tea.success)
        first = self.invoke(self.record, self.purchase_args(key="first"))
        second = self.invoke(self.record, self.purchase_args(key="second", quantity=2))
        self.assertEqual(first.data["items"][0]["item_id"], second.data["items"][0]["item_id"])
        self.assertEqual([first.data["items"][0]["inventory_after"], second.data["items"][0]["inventory_after"]], [1, 3])
        self.assertEqual([call["method"] for call in self.server.calls], ["POST"] * 3)
        self.assertEqual([call["payload"]["items"][0]["quantity"] for call in self.server.calls], [1, 1, 2])

    def test_alias_query_purchase_consume_and_absolute_adjust(self):
        alias = "零度可乐大瓶"
        self.plan("GET", "/api/v1/items/resolve?name=%E9%9B%B6%E5%BA%A6%E5%8F%AF%E4%B9%90%E5%A4%A7%E7%93%B6",
                  {"id": "cola-2l", "name": "无糖可乐", "spec": "2L", "quantity": 1})
        self.plan("POST", "/api/v1/purchases/record", summary(after=2))
        self.plan("POST", "/api/v1/items/consume", {"item": {"id": "cola-2l", "quantity": 1}})
        self.plan("POST", "/api/v1/items/adjust", {"id": "cola-2l", "quantity": 5})
        query = self.invoke(self.advanced, {"operation": "resolve_item", "query": {"name": alias}})
        purchase = self.invoke(self.record, self.purchase_args(name=alias, spec=""))
        consumed = self.invoke(self.inventory, {"action": "consume", "name": alias, "quantity": 1, "idempotency_key": "c"})
        adjusted = self.invoke(self.inventory, {"action": "adjust", "name": alias, "quantity": 5, "idempotency_key": "a"})
        self.assertTrue(all(r.success for r in [query, purchase, consumed, adjusted]))
        self.assertEqual(self.server.calls[-2]["payload"]["name"], alias)
        self.assertEqual(self.server.calls[-1]["payload"]["quantity"], 5)
        self.assertEqual(self.server.calls[-1]["payload"]["source"], "agent")
        self.assertEqual(len(self.server.calls), 4)

    def test_ambiguous_candidates_and_not_found_are_actionable(self):
        candidates = [{"id": "cola-2l", "name": "无糖可乐", "spec": "2L", "unit": "瓶", "current_quantity": 3},
                      {"id": "cola-500", "name": "无糖可乐", "spec": "500ml", "unit": "瓶", "current_quantity": 2}]
        ambiguous = error("ITEM_AMBIGUOUS", "商品有歧义", candidates=candidates)
        missing = error("ITEM_NOT_FOUND", "Item was not found", candidates=[])
        self.plan("POST", "/api/v1/items/consume", (409, ambiguous), (404, missing))
        args = {"action": "consume", "name": "无糖可乐", "quantity": 1, "idempotency_key": "ambiguous"}
        result = self.invoke(self.inventory, args)
        self.assertFalse(result.success)
        self.assertEqual(result.data, ambiguous)
        self.assertEqual(result.error, "ITEM_AMBIGUOUS")
        self.assertFalse(result.metadata["retryable"])
        for text in ["2L", "500ml", "cola-2l", "3瓶", "询问用户"]:
            self.assertIn(text, result.content)
        missing_result = self.invoke(self.inventory, {**args, "name": "不存在", "idempotency_key": "missing"})
        self.assertEqual(missing_result.data, missing)
        self.assertEqual(len(self.server.calls), 2)
        self.assertFalse(self.server.committed)

    def test_idempotent_purchase_inventory_and_maintenance(self):
        cases = [(self.record, self.purchase_args(), "/api/v1/purchases/record", summary()),
                 (self.advanced, {"operation": "add_maintenance_event", "item_id": "bike", "idempotency_key": "repair",
                                  "payload": {"title": "换后胎", "cost": 65, "source": "agent"}},
                  "/api/v1/items/bike/maintenance", {"id": "repair-1", "cost": 65})]
        for action in ["consume", "adjust", "open", "finish", "discard"]:
            args = {"action": action, "name": "无糖可乐", "idempotency_key": action}
            if action in {"consume", "adjust"}:
                args["quantity"] = 1
            cases.append((self.inventory, args, f"/api/v1/items/{action}", {"item": {"quantity": 1}, "event": {"type": action.upper()}}))
        for tool, args, path, response in cases:
            with self.subTest(path=path):
                self.plan("POST", path, response)
                first = self.invoke(tool, args)
                second = self.invoke(tool, args)
                self.assertTrue(first.success, first)
                self.assertEqual(first.data, second.data)
                self.assertTrue(second.metadata["idempotency_replayed"])
                self.assertEqual(self.server.calls[-2], self.server.calls[-1])
        self.assertEqual(len(self.server.committed), len(cases))

    def test_validate_has_no_key_write_or_unknown_outcome(self):
        preview = {**summary(), "purchase_id": ""}
        self.plan("POST", "/api/v1/purchases/validate", preview, preview)
        args = {"items": self.purchase_args()["items"]}
        for tool, data in [(self.validate, args), (self.advanced, {"operation": "validate_purchase", "payload": args})]:
            result = self.invoke(tool, data)
            self.assertTrue(result.success, result)
            self.assertIn("未写入", result.content)
            self.assertFalse(result.metadata["written"])
            self.assertIsNone(self.server.calls[-1]["key"])
            self.assertEqual(tool.permission_for(data), PermissionLevel.READ)
            self.assertEqual(tool.side_effects_for(data), frozenset({SideEffect.NONE}))
            self.assertTrue(tool.safe_to_replay(data))
        self.assertFalse(self.server.committed)
        with patch("tools.wubu_tool.client.build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError()
            for tool, data in [(self.validate, args), (self.advanced, {"operation": "validate_purchase", "payload": args})]:
                result = self.invoke(tool, data)
                self.assertFalse(result.success)
                self.assertFalse(result.metadata["unknown_outcome"])
        with patch("tools.wubu_tool.client.build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError()
            result = self.invoke(self.record, self.purchase_args())
            self.assertTrue(result.metadata["unknown_outcome"])
            opener.return_value.open.assert_called_once()

    def test_client_precheck_classification_and_server_retryable_are_preserved(self):
        client = WubuClient(self.url)
        with patch("tools.wubu_tool.client.build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError()
            from tools.wubu_tool.client import WubuError
            with self.assertRaises(WubuError) as caught:
                client.request("POST", "/api/v1/purchases/validate", payload={"items": []})
            self.assertFalse(caught.exception.unknown)
        response = error("RECHECK_INPUT", "needs review")
        response["error"]["retryable"] = True
        response["error"]["suggested_action"] = "review_purchase_input"
        self.plan("POST", "/api/v1/purchases/record", (422, response))
        result = self.invoke(self.record, self.purchase_args())
        self.assertFalse(result.success)
        self.assertTrue(result.metadata["retryable"])
        self.assertEqual(result.data, response)
        self.assertFalse(result.metadata["unknown_outcome"])
        self.assertEqual(len(self.server.calls), 1)

    def test_full_dto_dry_run_read_only(self):
        self.plan("POST", "/api/v1/purchases?dry_run=true", {**summary(), "purchase_id": ""})
        args = {"operation": "record_purchase_event", "query": {"dry_run": True},
                "payload": {"total_amount": 5.5, "items": [{"name": "无糖可乐", "spec": "2L", "quantity": 1,
                         "unit": "瓶", "unit_price": 5.5, "subtotal": 5.5}]}}
        result = self.invoke(self.advanced, args)
        self.assertTrue(result.success, result)
        self.assertEqual(self.advanced.permission_for(args), PermissionLevel.READ)
        self.assertIsNone(self.server.calls[0]["key"])
        self.assertIn("未写入", result.content)

    def test_warnings_remain_visible_and_exact(self):
        warned = summary(added=2, amount=5.5)
        warned["validation_status"] = "WARNING"
        warned["warnings"] = [{"code": "PURCHASE_AMOUNT_INCONSISTENT", "message": "total differs", "line": 1},
                              {"code": "SPEC_QUANTITY_CONFLICT", "message": "check spec", "line": 1}]
        self.plan("POST", "/api/v1/purchases/record", warned)
        result = self.invoke(self.record, {**self.purchase_args(quantity=2), "total": 5.5})
        self.assertTrue(result.success)
        self.assertEqual(result.data, warned)
        for phrase in ["PURCHASE_AMOUNT_INCONSISTENT", "SPEC_QUANTITY_CONFLICT", "请核对", "WARNING"]:
            self.assertIn(phrase, result.content)

    def test_amend_delete_preserve_version_key_source_and_row_ids(self):
        original = {"id": "purchase-1", "updated_at": "2026-10-06T02:00:00Z", "source": "import", "external_id": "order-123",
                    "total_amount": 5.5, "items": [{"id": "line-1", "item_id": "cola-2l", "name": "无糖可乐", "spec": "2L",
                                                    "quantity": 1, "unit": "瓶", "unit_price": 5.5, "subtotal": 5.5}]}
        self.plan("GET", "/api/v1/purchases/purchase-1", original)
        read = self.invoke(self.advanced, {"operation": "get_purchase_event", "purchase_id": "purchase-1"})
        payload = {k: deepcopy(read.data[k]) for k in ["source", "external_id", "items", "total_amount"]}
        payload["expected_updated_at"] = read.data["updated_at"]
        payload["note"] = "补备注"
        self.plan("PUT", "/api/v1/purchases/purchase-1", {**summary(), "updated_at": "2026-10-06T02:01:00Z"})
        args = {"operation": "amend_purchase_event", "purchase_id": "purchase-1", "idempotency_key": "amend", "payload": payload}
        first, repeat = self.invoke(self.advanced, args), self.invoke(self.advanced, args)
        self.assertTrue(first.success, first)
        self.assertTrue(repeat.metadata["idempotency_replayed"])
        self.assertEqual(self.server.calls[-1]["payload"], payload)
        self.assertEqual(self.server.calls[-1], self.server.calls[-2])
        self.assertEqual(len(self.server.calls), 3) # no implicit refresh of expected version
        self.plan("DELETE", "/api/v1/purchases/purchase-1", {"deleted": True, "purchase_id": "purchase-1"})
        deletion = {"operation": "delete_purchase_event", "purchase_id": "purchase-1", "idempotency_key": "delete",
                    "payload": {"expected_updated_at": "2026-10-06T02:01:00Z"}}
        deleted, replay = self.invoke(self.advanced, deletion), self.invoke(self.advanced, deletion)
        self.assertTrue(deleted.success)
        self.assertTrue(replay.metadata["idempotency_replayed"])
        self.assertEqual(self.server.calls[-1]["payload"], deletion["payload"])
        for invocation in [args, deletion]:
            self.assertEqual(self.advanced.permission_for(invocation), PermissionLevel.WRITE)
            self.assertEqual(self.advanced.side_effects_for(invocation), frozenset({SideEffect.LOCAL_STATE}))
            self.assertTrue(self.advanced.default_confirm_write)
        self.plan("PUT", "/api/v1/purchases/other", (409, error("STALE_PURCHASE", "expected version mismatch")))
        stale = self.invoke(self.advanced, {**args, "purchase_id": "other", "idempotency_key": "stale"})
        self.assertFalse(stale.success)
        self.assertFalse(stale.metadata["retryable"])
        self.assertFalse(stale.metadata["unknown_outcome"])

    def test_sdk_discovery_and_actual_simple_schemas(self):
        package = next(p for p in discover_tool_packages() if p.package_id == "wubu-tool")
        tools = package.create_tools({"base_url": self.url, "autostart_enabled": False})
        self.assertEqual([t.name for t in tools][:4], ["record_purchase", "validate_purchase", "wubu_inventory_event", "wubu"])
        self.assertEqual(package.package_version, "0.2.1")
        schemas = {t.name: t.schema()["function"]["parameters"] for t in tools}
        record = schemas["record_purchase"]
        self.assertEqual(set(record["required"]), {"items", "idempotency_key"})
        self.assertNotIn("operation", record["properties"])
        self.assertNotIn("payload", record["properties"])
        line = next(iter(record["$defs"].values()))
        self.assertEqual(set(line["required"]), {"name", "quantity", "unit"})
        self.assertEqual(set(line["properties"]), {"name", "quantity", "unit", "price", "spec", "item_type", "location"})
        for name in ["record_purchase", "validate_purchase", "wubu_inventory_event"]:
            self.assertNotIn('"null"', json.dumps(schemas[name]))
        self.assertEqual(schemas["validate_purchase"]["required"], ["items"])
        self.assertNotIn("idempotency_key", schemas["validate_purchase"]["properties"])
        for operation in ["get_purchase_event", "amend_purchase_event", "delete_purchase_event"]:
            branch = next(b for b in schemas["wubu"]["oneOf"] if b["properties"]["operation"]["const"] == operation)
            self.assertIn("purchase_id", branch["required"])
            self.assertNotIn("item_id", branch["properties"])
        self.assertEqual(set(CONTRACT), OPERATIONS)

    def test_invalid_simple_inputs_do_not_make_requests(self):
        for args in [self.purchase_args(quantity=0), self.purchase_args(price=-1), self.purchase_args(price=5.555),
                     self.purchase_args(name=" "), {"items": [], "idempotency_key": "k"},
                     {"items": self.purchase_args()["items"]}, {**self.purchase_args(), "operation": "record"}]:
            self.assertFalse(self.invoke(self.record, args).success)
        for args in [{"action": "consume", "name": "可乐", "quantity": 0, "idempotency_key": "k"},
                     {"action": "adjust", "name": "可乐", "idempotency_key": "k"},
                     {"action": "finish", "name": "可乐", "quantity": 1, "idempotency_key": "k"}]:
            self.assertFalse(self.invoke(self.inventory, args).success)
        self.assertFalse(self.server.calls)
        for operation in ["amend_purchase_event", "delete_purchase_event"]:
            result = self.invoke(self.advanced, {"operation": operation, "item_id": "wrong-field",
                "idempotency_key": "key", "payload": {"expected_updated_at": "2026-10-06T02:00:00Z"}})
            self.assertFalse(result.success)
        self.assertFalse(self.server.calls)


if __name__ == "__main__":
    unittest.main()
