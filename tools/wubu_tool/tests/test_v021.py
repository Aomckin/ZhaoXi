"""v0.2.1 SDK contract and HTTP adapter regression tests."""
import asyncio
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from zhaoxi.sdk import PermissionLevel, SideEffect
from tools.wubu_tool.tests.test_v011 import ScriptedHandler, error
from tools.wubu_tool.package import WubuToolPackage
from tools.wubu_tool.ledger_tools import OPERATIONS
from tools.wubu_tool.tool import CONTRACT
from tools.wubu_tool.client import WubuClient

ScriptedHandler.do_PATCH = ScriptedHandler.reply

class V021Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),ScriptedHandler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
    def setUp(self):
        self.server.calls,self.server.committed,self.server.responses=[],{},{}
        self.tools={t.name:t for t in WubuToolPackage().create_tools({
            "base_url":f"http://127.0.0.1:{self.server.server_port}","autostart_enabled":False})}
    def invoke(self,name,**args):
        return asyncio.run(self.tools[name].run(args))
    def plan(self,method,path,data,status=200):
        self.server.responses[(method,path)]=[(status,data)]
    def test_discovery_descriptions_and_flat_schema(self):
        self.assertEqual(len(CONTRACT),65)
        self.assertEqual(len(self.tools),37)
        for name in OPERATIONS:
            tool=self.tools[name]
            props=tool.input_model.model_json_schema()["properties"]
            self.assertNotIn("payload",props)
            self.assertNotIn("source",props)
            self.assertIn("【给朝汐的调用注释】",tool.description)
    def test_all_new_permissions_and_stable_key_requirement(self):
        for name,op in OPERATIONS.items():
            t=self.tools[name]
            read=CONTRACT[op]["method"]=="GET"
            self.assertEqual(t.permission,PermissionLevel.READ if read else PermissionLevel.WRITE)
            self.assertEqual(t.side_effects,frozenset({SideEffect.NONE if read else SideEffect.LOCAL_STATE}))
            self.assertEqual(t.safe_to_replay({}),read)
            self.assertTrue(t.safe_to_replay({"idempotency_key":"stable"}))
            if not read:
                self.assertIn("idempotency_key",t.input_model.model_json_schema()["required"])
    def test_topup_same_key_replay_and_conflict(self):
        path=CONTRACT["top_up_account"]["path"]
        self.plan("POST",path,{"transactions":[]})
        args=dict(from_account="wallet",to_account="tea",paid_amount=100,credited_amount=110,idempotency_key="stable")
        self.assertTrue(self.invoke("top_up_account",**args).success)
        replay=self.invoke("top_up_account",**args)
        self.assertTrue(replay.metadata["idempotency_replayed"])
        self.assertFalse(self.invoke("top_up_account",**{**args,"credited_amount":111}).success)
        self.assertEqual(self.server.calls[0]["payload"]["source"],"agent")
        self.assertEqual([c["key"] for c in self.server.calls],["stable"]*3)
    def test_account_path_encoded_and_patch(self):
        path="/api/v1/accounts/a%2Fb%3Fc"
        self.plan("PATCH",path,{"id":"a/b?c"})
        self.assertTrue(self.invoke("update_account",account_id="a/b?c",active=False,idempotency_key="patch").success)
        self.assertEqual(self.server.calls[0]["path"],path)
        self.assertEqual(self.server.calls[0]["payload"],{"active":False})
    def test_query_boolean_and_bonus_filter(self):
        self.plan("GET","/api/v1/accounts?active=false",{"items":[]})
        self.assertTrue(self.invoke("get_accounts",active=False).success)
        self.plan("GET","/api/v1/money/transactions?type=BONUS",{"items":[]})
        self.assertTrue(self.invoke("get_recent_transactions",type="BONUS").success)
    def test_semantic_rejections_send_no_requests(self):
        samples=[
            ("record_refund",dict(amount=1,idempotency_key="x")),
            ("top_up_account",dict(from_account="x",to_account="x",paid_amount=1,credited_amount=1,idempotency_key="x")),
            ("add_maintenance",dict(item_id="x",title="fix",cost=1,status="PLANNED",idempotency_key="x")),
            ("get_money_summary",dict(period="month",**{"from":"2026-01-01T00:00:00Z"})),
            ("set_durable_status",dict(item_id="x",status="SOLD",idempotency_key="x")),
        ]
        for name,args in samples:
            self.assertFalse(self.invoke(name,**args).success)
        self.assertEqual(self.server.calls,[])
    def test_warnings_preserved_and_explained(self):
        for name,op,code,args in [
            ("top_up_account","top_up_account","TOP_UP_VALUE_LOSS",dict(from_account="a",to_account="b",paid_amount=10,credited_amount=8)),
            ("update_account","update_account","ACCOUNT_HAS_REMAINING_BALANCE",dict(account_id="a",active=False)),
        ]:
            data={"warnings":[{"code":code,"message":"check"}]}
            path=CONTRACT[op]["path"].replace("{id}","a")
            self.plan(CONTRACT[op]["method"],path,data)
            result=self.invoke(name,**args,idempotency_key=name)
            self.assertTrue(result.success)
            self.assertEqual(result.data,data)
            self.assertIn("核对",result.content)
    def test_merchant_conflict_and_refund_original_reference(self):
        path=CONTRACT["record_expense"]["path"]
        data=error("ACCOUNT_MERCHANT_MISMATCH","wrong merchant")
        self.plan("POST",path,data,409)
        result=self.invoke("record_expense",amount=1,account_id="a",merchant="wrong",idempotency_key="expense")
        self.assertFalse(result.success)
        self.assertEqual(result.data,data)
        self.assertIn("核对",result.content)
        self.plan("POST",CONTRACT["record_refund"]["path"],{"transactions":[]})
        self.assertTrue(self.invoke("record_refund",amount=1,purchase_event_id="original",account_id="other",idempotency_key="refund").success)
        self.assertEqual(self.server.calls[-1]["payload"]["purchase_event_id"],"original")
        self.assertEqual(self.server.calls[-1]["payload"]["account_id"],"other")
