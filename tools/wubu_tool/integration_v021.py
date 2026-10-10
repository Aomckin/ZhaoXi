"""SDK to real isolated Wubu acceptance; requires explicit isolated-write opt-in."""
import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit
from tools.wubu_tool.client import WubuClient
from tools.wubu_tool.package import WubuToolPackage

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--allow-isolated-writes", action="store_true")
    args = parser.parse_args()
    url = urlsplit(args.base_url)
    if not args.allow_isolated_writes or url.hostname != "127.0.0.1" or url.port != 12555:
        parser.error("Only explicitly authorized isolated 127.0.0.1:12555 is allowed.")
    client = WubuClient(args.base_url, autostart=False)
    health, _ = client.request("GET", "/healthz")
    assert health["version"] == "0.2.1", health
    tools = {t.name:t for t in WubuToolPackage().create_tools({"base_url":args.base_url,"autostart_enabled":False})}
    tag = uuid4().hex
    report = {"health":health,"base_url":args.base_url,"autostart":False,"run_id":tag,"checks":[],"calls":[]}
    def check(label, condition, detail=None):
        report["checks"].append({"name":label,"passed":bool(condition),"detail":detail})
        assert condition, (label, detail)
    def call(tool_name, expected=True, **values):
        if tool_name != "wubu" and tools[tool_name].permission.value != "read" and "idempotency_key" in tools[tool_name].input_model.model_fields:
            values.setdefault("idempotency_key", tag + "-" + str(len(report["calls"])))
        result = asyncio.run(tools[tool_name].run(values))
        report["calls"].append({"tool":tool_name,"input":values,"result":result.model_dump(mode="json")})
        check(tool_name+" response", result.success == expected, result.model_dump(mode="json") if result.success != expected else None)
        return result
    def account(name, **kw):
        data=call("create_account",name=tag+name,**kw).data
        return data.get("account",data)["id"]
    def balance(a):
        d=call("get_account",account_id=a).data
        return d.get("account",d)["current_balance"]
    try:
        baseline=call("get_balance").data
        wallet=account("wallet",initial_balance=500,account_class="STORAGE")
        tea=account("tea",type="MERCHANT_BALANCE",account_class="CONSUMPTION",merchant=tag+"merchant")
        call("set_default_payment_account",default_payment_account=wallet)
        top={"from_account":wallet,"to_account":tea,"paid_amount":100,"credited_amount":110,"idempotency_key":tag+"top"}
        first=call("top_up_account",**top)
        again=call("top_up_account",**top)
        check("stable top-up replay", again.data == first.data and again.metadata["idempotency_replayed"])
        check("100 paid 110 credited",balance(wallet)==400 and balance(tea)==110)
        check("top-up three transaction types",sorted(t["type"] for t in first.data["transactions"])==["BONUS","TRANSFER_IN","TRANSFER_OUT"])
        income=call("get_income_summary",account_id=tea).data
        check("bonus not ordinary income",income.get("income",income.get("total_income",income.get("total_amount",0)))==0,income)
        purchase=call("record_purchase",account_id=tea,items=[{"name":tag+"tea","quantity":1,"unit":"杯","price":20,"item_type":"UNTRACKED"}]).data
        check("consume 20",balance(tea)==90)
        call("record_refund",amount=10,purchase_event_id=purchase["purchase_id"])
        check("refund defaults original account",balance(tea)==100)
        call("record_refund",amount=5,purchase_event_id=purchase["purchase_id"],account_id=wallet)
        check("cross-account refund",balance(wallet)==405 and balance(tea)==100)
        stats=call("get_account_statistics",account_id=tea).data
        check("account statistics",all(stats.get(k)==v for k,v in {"top_up_principal":100,"bonus":10,"expense":20,"refund":15,"net_expense":5,"current_balance":100,"bonus_ratio":0.1}.items()),stats)
        b=call("get_balance").data
        check("classified balances",b["liquid_balance"]-baseline["liquid_balance"]==405 and b["consumption_balance"]-baseline["consumption_balance"]==100,b)
        history=call("get_recent_transactions",account_id=tea).data
        call("update_account",account_id=tea,account_class="STORAGE")
        b=call("get_balance").data
        check("class edit moves current balance",b["liquid_balance"]-baseline["liquid_balance"]==505 and b["consumption_balance"]==baseline["consumption_balance"],b)
        check("class edit preserves history",call("get_recent_transactions",account_id=tea).data==history)
        call("update_account",account_id=tea,account_class="CONSUMPTION")
        inactive=call("update_account",account_id=tea,active=False)
        check("deactivation remaining balance warning","ACCOUNT_HAS_REMAINING_BALANCE" in json.dumps(inactive.data) and "核对" in inactive.content,inactive.data)
        call("update_account",account_id=tea,active=True)
        mismatch=call("record_expense",expected=False,account_id=tea,amount=1,merchant="wrong")
        check("merchant mismatch actionable",mismatch.error=="ACCOUNT_MERCHANT_MISMATCH" and "核对" in mismatch.content)
        loss=call("top_up_account",from_account=wallet,to_account=tea,paid_amount=10,credited_amount=8)
        check("short credit warning","TOP_UP_VALUE_LOSS" in json.dumps(loss.data),loss.data)
        call("record_bonus",account_id=tea,amount=2)
        call("record_bonus",expected=False,account_id=wallet,amount=2)
        call("get_recent_transactions",type="BONUS")
        d=call("record_purchase",account_id=wallet,items=[{"name":tag+"keyboard","quantity":1,"unit":"个","price":399,"item_type":"DURABLE","location":"desk"}]).data
        item=d["items"][0]["item_id"]
        before_maintenance=balance(wallet)
        call("add_maintenance",item_id=item,title="repair",cost=50,account_id=wallet)
        check("maintenance atomically deducts 50",balance(wallet)==before_maintenance-50)
        cost=call("get_item_total_cost",item_id=item).data
        check("purchase plus maintenance cost",cost.get("total_cost")==449,cost)
        call("move_item",item_id=item,location="shelf")
        for status in ["STORED","LOST","ACTIVE"]:
            call("set_durable_status",item_id=item,status=status)
            current=call("wubu",operation="get_item",item_id=item).data
            check("durable "+status+" inventory",current["quantity"]==(0 if status=="LOST" else 1),current)
        sale={"item_id":item,"amount":260,"account_id":wallet,"idempotency_key":tag+"sale"}
        before_sale=balance(wallet)
        sold=call("sell_item",**sale)
        check("sale credits 260",balance(wallet)==before_sale+260)
        check("sale replay",call("sell_item",**sale).data==sold.data)
        check("sale replay no duplicate income",balance(wallet)==before_sale+260)
        call("set_durable_status",expected=False,item_id=item,status="ACTIVE")
        d=call("record_purchase",account_id=wallet,items=[{"name":tag+"mouse","quantity":1,"unit":"个","price":10,"item_type":"DURABLE"}]).data
        retired=d["items"][0]["item_id"]
        call("retire_item",item_id=retired)
        call("set_durable_status",expected=False,item_id=retired,status="ACTIVE")
        call("get_durable_history",item_id=item)
        call("get_durable_items",status="SOLD")
        call("get_recent_maintenance")
        call("record_income",account_id=wallet,amount=20)
        call("record_expense",account_id=wallet,amount=2)
        call("transfer_money",from_account=wallet,to_account=tea,amount=1)
        call("adjust_balance",account_id=wallet,actual_balance=4321.08,reason="acceptance")
        check("absolute adjustment",balance(wallet)==4321.08)
        call("reconcile_account",account_id=wallet,actual_balance=4320.08,reason="acceptance")
        check("absolute reconcile",balance(wallet)==4320.08)
        call("save_money_category",name=tag+"category")
        for name in ["get_money_categories","get_money_summary","get_expense_summary","get_income_summary","get_category_summary","get_merchant_summary","get_money_settings"]:
            call(name)
        call("get_accounts",account_class="CONSUMPTION",merchant=tag+"merchant",active=True)
    finally:
        report["passed"]=sum(c["passed"] for c in report["checks"])
        report["total"]=len(report["checks"])
        Path(__file__).with_name("INTEGRATION_V0.2.1.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("isolated checks:",report["passed"],"/",report["total"])
if __name__ == "__main__":
    main()
