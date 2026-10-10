"""Refresh the curated contract from Wubu's local OpenAPI (read-only HTTP)."""
import json
from pathlib import Path

from tools.wubu_tool.client import WubuClient


OPERATIONS = frozenset("""
record_purchase_event consume_item adjust_inventory open_item finish_item discard_item
add_maintenance_event search_items resolve_item get_item get_inventory get_purchase_history
get_price_history get_maintenance_history get_inventory_history get_item_inventory_history
get_recent_purchases get_purchase_event get_expenses get_ledger_summary get_durable_details
update_durable_details add_product_alias get_product_aliases
amend_purchase_event delete_purchase_event record_purchase validate_purchase
consume_by_name adjust_by_name open_by_name finish_by_name discard_by_name
get_accounts create_account get_account update_account get_money_settings set_default_payment_account
get_balance record_expense record_income transfer_money record_refund adjust_balance reconcile_account
get_recent_transactions get_money_summary get_expense_summary get_income_summary get_category_summary
get_merchant_summary get_money_categories save_money_category get_durable_items sell_item retire_item
move_item set_durable_status get_durable_history get_item_total_cost get_recent_maintenance
top_up_account record_bonus get_account_statistics
""".split())


def build_contract(document):
    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            target = document
            for part in value["$ref"].removeprefix("#/").split("/"):
                target = target[part]
            return expand({**target, **{k: v for k, v in value.items() if k != "$ref"}})
        return {key: expand(item) for key, item in value.items()}

    def request_schema(value):
        """Exclude response-only fields; clarify the service's legacy unit help text."""
        if isinstance(value, list):
            return [request_schema(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: request_schema(item) for key, item in value.items()}
        if "properties" in result:
            properties = {key: item for key, item in result["properties"].items() if not item.get("readOnly")}
            result["properties"] = properties
            if "required" in result:
                result["required"] = [key for key in result["required"] if key in properties]
            if "spec" in properties and "unit" in properties:
                properties["unit"]["description"] = "库存计数单位，如瓶、包、个；包装规格单独填spec或package_size/package_unit。"
        return result

    result = {}
    for path, methods in document["paths"].items():
        for method, definition in methods.items():
            if not isinstance(definition, dict):
                continue
            name = definition.get("operationId")
            if name not in OPERATIONS:
                continue
            params = [expand(p) for p in methods.get("parameters", []) + definition.get("parameters", [])]
            query = {p["name"]: p["schema"] for p in params if p.get("in") == "query"}
            result[name] = {
                "method": method.upper(), "path": path,
                "query": {"type": "object", "properties": query, "additionalProperties": False,
                          "required": [p["name"] for p in params if p.get("in") == "query" and p.get("required")]},
                "payload": request_schema(expand(definition.get("requestBody", {}).get("content", {})
                                  .get("application/json", {}).get("schema", {}))),
                "idempotent": any(p.get("name") == "Idempotency-Key" for p in params),
            }
    if set(result) != OPERATIONS:
        raise ValueError(f"Missing operations: {OPERATIONS - set(result)}")
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8026")
    parser.add_argument("--openapi-file", help="Read the local versioned contract instead of a possibly older running server")
    args = parser.parse_args()
    if args.openapi_file:
        document = json.loads(Path(args.openapi_file).read_text(encoding="utf-8"))
    else:
        document, _ = WubuClient(args.base_url).request("GET", "/api/v1/openapi.json")
    contract = build_contract(document)
    Path(__file__).with_name("contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Synced {len(contract)} operations")


if __name__ == "__main__":
    main()
