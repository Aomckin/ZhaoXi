"""Read/validate-only v0.2.1 checks. Never starts services or sends event writes."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from tools.wubu_tool.client import WubuClient
from tools.wubu_tool.package import create_package
from tools.wubu_tool.sync_schema import build_contract
from tools.wubu_tool.tool import CONTRACT


def snapshot(client):
    result = {}
    for path in ["/api/v1/items", "/api/v1/purchases", "/api/v1/expenses", "/api/v1/inventory-events"]:
        rows = []
        offset = 0
        while True:
            data, _ = client.request("GET", path, {"limit": 500, "offset": offset})
            page = data["items"]
            rows.extend(page)
            if len(page) < 500:
                break
            offset += 500
        encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        result[path] = {"count": len(rows), "sha256": hashlib.sha256(encoded).hexdigest()}
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8026")
    args = parser.parse_args()
    client = WubuClient(args.base_url)
    health, _ = client.request("GET", "/healthz")
    assert health["status"] == "ok" and health["version"] == "0.2.1", health
    document, _ = client.request("GET", "/api/v1/openapi.json")
    assert build_contract(document) == CONTRACT, "Run sync_schema before verifying"
    package = create_package()
    tools = package.create_tools({"base_url": args.base_url, "autostart_enabled": False})
    validator = next(t for t in tools if t.name == "validate_purchase")
    before = snapshot(client)
    examples = [
        {"items": [{"name": "无糖可乐", "spec": "2L", "quantity": 1, "unit": "瓶", "price": 5.5}]},
        {"items": [{"name": "东方树叶", "spec": "900ml", "quantity": 1, "unit": "瓶", "price": 5}]},
        {"items": [{"name": "无糖可乐", "spec": "2000ml", "quantity": 1, "unit": "瓶", "price": 5.5}]},
        {"items": [{"name": "朝汐预检查样例饮料", "spec": "2L", "quantity": 2, "unit": "L", "price": 5.5}], "total": 5.5},
    ]
    outcomes = []
    for arguments in examples:
        outcome = asyncio.run(validator.run(arguments))
        assert outcome.success, (arguments, outcome)
        assert outcome.metadata["written"] is False
        assert outcome.metadata["unknown_outcome"] is False
        outcomes.append({"input": arguments, "result": outcome.model_dump()})
    two_liters = outcomes[0]["result"]["data"]["items"][0]
    equivalent = outcomes[2]["result"]["data"]["items"][0]
    assert two_liters.get("item_id") == equivalent.get("item_id"), "Equivalent specs resolved differently"
    warnings = {w["code"] for w in outcomes[3]["result"]["data"]["warnings"]}
    assert {"PURCHASE_AMOUNT_INCONSISTENT", "SPEC_QUANTITY_CONFLICT"} <= warnings, warnings
    after = snapshot(client)
    assert before == after, "Public entity snapshots changed; inspect concurrent activity before drawing conclusions"
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(), "health": health,
        "operations": len(CONTRACT), "tools": [t.name for t in tools],
        "scope": "Real v0.2.1: GET and POST /purchases/validate only; no event writes, no restart. Public API entity snapshots, not a byte-level database checksum.",
        "before": before, "after": after, "public_entities_unchanged": before == after,
        "prechecks": outcomes,
        "schemas": {t.name: t.schema() for t in tools if t.name != "wubu"},
    }
    output = Path(__file__).with_name("LIVE_VERIFICATION_V0.2.1.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"v0.2.1: {len(outcomes)} live prechecks passed; public entities unchanged; report: {output}")


if __name__ == "__main__":
    main()
