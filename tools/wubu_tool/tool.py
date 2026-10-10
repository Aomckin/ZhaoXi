"""Operation-based Wubu tool, with the DTO contract visible to Zhaoxi."""
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, model_validator
from zhaoxi.sdk import PermissionLevel, SideEffect, Tool, ToolResult

from tools.wubu_tool.client import WubuClient
from tools.wubu_tool.zhaoxi_notes import ZHAOXI_NOTES
from tools.wubu_tool.results import perform

CONTRACT = json.loads(Path(__file__).with_name("contract.json").read_text(encoding="utf-8"))
Operation = Literal[tuple(CONTRACT)]
PURCHASE_ID_OPERATIONS = frozenset({"get_purchase_event", "amend_purchase_event", "delete_purchase_event"})


def path_id_field(operation):
    path = CONTRACT[operation]["path"]
    if operation in PURCHASE_ID_OPERATIONS:
        return "purchase_id"
    return "account_id" if path.startswith("/api/v1/accounts/") else "item_id"


def read_only_operation(arguments):
    operation = arguments["operation"]
    return (CONTRACT[operation]["method"] == "GET" or operation == "validate_purchase"
            or (operation == "record_purchase_event" and arguments.get("query", {}).get("dry_run") in (True, "true")))

# These notes are exported in the function schema, so Zhaoxi can read them.
# Python comments alone are not part of the model's tool context.
OPERATION_NOTES = {
    "record_purchase_event": (
        "高级完整DTO购买，用于复杂账单；购买含耐用品或服务均优先独立 record_purchase。"
        "同时创建购买事件、费用和商品/库存。首次购买无需预先查到商品，"
        "新商品在 payload.items 中填写 name 并省略 item_id；物簿负责匹配已有商品或创建新商品。"
        "resolve_item 返回404/not_found时，普通首次购买继续独立record_purchase；高级完整DTO可继续本操作。"
        "使用用户提供的数量、单位和金额；必要信息不明确时询问，不编造。"
    ),
    "resolve_item": (
        "按名称/别名定位已存在的物品，不创建商品、不记录购买。404/not_found 仅表示未找到已有物品；"
        "若任务是普通首次购买记账，改用独立 record_purchase；复杂完整DTO才用record_purchase_event。"
        "若任务是消耗、调整或维护，则先核实对象；409 歧义需要用户明确物品。"
    ),
    "search_items": "搜索已有商品。空列表不阻止新购买；普通首次购买用独立 record_purchase 自动匹配或创建。",
    "consume_item": "消耗已有物品，必须定位 item_id；quantity 是本次消耗量，不能把消费金额填进数量。",
    "adjust_inventory": "纠正已有物品的库存；quantity 是实际剩余量。此操作不能代替购买记账。",
    "record_purchase": "常用购买优先调用独立 record_purchase 工具，省去 operation/payload 层级。包装规格单独填 spec。",
    "validate_purchase": "纯读取购买预检查，无幂等键，不生成物品或账目；通过不等于已记账。",
    "get_purchase_event": "改单或删除前先读取购买明细，获取 updated_at、source、external_id、商品行 id/item_id。",
    "amend_purchase_event": (
        "先 get_purchase_event 读取完整购买，提交 expected_updated_at=刚读取的 updated_at。"
        "保留原 source、external_id 和保留商品行的 id/item_id，按完整DTO一次改单，费用和库存差额由后端同事务更新。"
        "重试保持原版本、原键和完全相同的DTO；409需核对，不自动重新取版本或换键。"
    ),
    "delete_purchase_event": (
        "先 get_purchase_event 获取 updated_at，提交 expected_updated_at 和稳定幂等键；"
        "后端同事务撤销费用与购买库存贡献，保留审计历史。重试保持原版本和原键，不拆成删费用/改库存。"
    ),
}


def input_contract(schema):
    branches = []
    for operation, spec in CONTRACT.items():
        notes = OPERATION_NOTES.get(operation)
        properties = {"operation": {"const": operation, **({"description": notes} if notes else {})},
                      "query": spec["query"]}
        required = ["operation"]
        if spec["query"].get("required"):
            required.append("query")
        if "{id}" in spec["path"]:
            field = path_id_field(operation)
            properties[field] = {"type": "string", "minLength": 1, "maxLength": 200}
            required.append(field)
        if spec["method"] != "GET":
            properties["payload"] = spec["payload"]
            if operation != "validate_purchase":
                properties["idempotency_key"] = {"type": "string", "minLength": 1, "maxLength": 200,
                    "description": "每个现实事件稳定保存一个键；重试复用原键和完全相同的参数，409 不换键重发。"}
                required.append("idempotency_key")
            if spec["payload"].get("required") or spec["payload"].get("oneOf"):
                required.append("payload")
        if operation == "get_inventory_history":
            properties["item_id"] = {"type": "string", "minLength": 1, "maxLength": 200}
        branch = {"type": "object", "properties": properties, "required": required,
                  "additionalProperties": False}
        if notes:
            branch["description"] = notes
        if operation == "record_purchase_event":
            branch["examples"] = [{"operation": operation, "idempotency_key": "purchase-example-001",
                "payload": {"total_amount": 5.5, "currency": "CNY", "source": "agent",
                    "items": [{"name": "无糖可乐", "spec": "2L", "quantity": 1, "unit": "瓶",
                               "unit_price": 5.5, "subtotal": 5.5, "item_type": "CONSUMABLE"}]}}]
            if "dry_run" in spec["query"]["properties"]:
                preview = deepcopy(branch)
                preview["properties"].pop("idempotency_key")
                preview["required"].remove("idempotency_key")
                preview["required"].append("query")
                preview["properties"]["query"]["properties"]["dry_run"] = {"const": True}
                preview["properties"]["query"]["required"] = ["dry_run"]
                preview["description"] = "完整DTO纯读取预检查，dry_run=true，不需要幂等键。"
                branches.append(preview)
                branch = deepcopy(branch)
                branch["properties"]["query"]["properties"]["dry_run"] = {"const": False}
        branches.append(branch)
    schema["oneOf"] = branches


class WubuInput(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra=input_contract)
    operation: Operation = Field(description="常用购买优先独立 record_purchase；此高级入口兼容原购买及耐用品、维护、改单删除。")
    item_id: str | None = Field(default=None, min_length=1, max_length=200)
    purchase_id: str | None = Field(default=None, min_length=1, max_length=200)
    account_id: str | None = Field(default=None, min_length=1, max_length=200)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200,
                                       pattern=r"^[\x21-\x7e]+$")
    query: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict,
        description="写操作的业务 DTO，见对应分支。首次购买用 items 商品行的 name 创建商品，无需已有 item_id。")

    @model_validator(mode="after")
    def validate_operation(self):
        spec = CONTRACT[self.operation]
        write = not read_only_operation(self.model_dump())
        if "{id}" in spec["path"]:
            identifier = getattr(self, path_id_field(self.operation))
            if not identifier or not identifier.strip() or identifier in {".", ".."}:
                raise ValueError("此操作必须提供明确的 item_id 或 purchase_id。")
        allowed_ids = {path_id_field(self.operation)} if "{id}" in spec["path"] else (
            {"item_id"} if self.operation == "get_inventory_history" else set())
        if any(getattr(self, field) is not None and field not in allowed_ids
               for field in ("item_id", "purchase_id", "account_id")):
            raise ValueError("此操作不接受所提供的 ID。")
        if write and not self.idempotency_key:
            raise ValueError("写操作必须提供稳定的 idempotency_key。")
        if spec["method"] == "GET" and (self.payload or self.idempotency_key):
            raise ValueError("查询操作不接受 payload 或 idempotency_key。")
        if not write and self.idempotency_key:
            raise ValueError("纯读取预检查不接受 idempotency_key。")
        query_schema = spec["query"]
        if set(self.query) - set(query_schema["properties"]):
            raise ValueError("query 包含此操作不支持的字段。")
        if set(query_schema.get("required", [])) - set(self.query):
            raise ValueError("query 缺少必填字段。")
        if any(v is None or not isinstance(v, (str, int, float, bool)) for v in self.query.values()):
            raise ValueError("query 字段必须是非空的标量。")
        if spec["method"] != "GET":
            dto = spec["payload"]
            if set(dto.get("required", [])) - set(self.payload):
                raise ValueError("payload 缺少必填字段，见 operation 对应 DTO。")
            if dto.get("additionalProperties") is False and set(self.payload) - set(dto["properties"]):
                raise ValueError("payload 包含此操作不支持的字段。")
        # Reject non-JSON values before any request is sent. Business validation belongs to Wubu.
        json.dumps({"query": self.query, "payload": self.payload}, allow_nan=False)
        return self


class WubuTool(Tool):
    name = "wubu"
    aliases = ("物簿", "库存账簿")
    intents = ("记录购买", "查询库存", "消耗物品", "纠正库存", "记录维修", "查询支出", "查询物品价格")
    description = ZHAOXI_NOTES + (
        "调用物簿记录购买、消耗、实际剩余库存、开封、用完、丢弃、维修，以及查询物品、别名、历史和支出。"
        "常用购买优先独立 record_purchase，预检查用 validate_purchase，按名称/规格/别名的库存动作优先 wubu_inventory_event。"
        "本高级入口保留旧调用和完整DTO；新账户、资金、充值、赠送、退款和耐用品动作优先同名独立工具。"
        "get_balance的liquid_balance是自由资金，consumption_balance是受限消费储值，不能混为可用现金。"
        "top_up_account一次原子充值；record_bonus仅消费账户，赠送不算收入。账户路径填account_id。"
        "购买和费用记账使用物簿，不用 LifeHUD 生活记录代替。"
        "operation 选择动作，payload/query 的完整 DTO 见对应 oneOf 分支。"
        "购买含耐用品或服务均可用独立 record_purchase；复杂完整DTO才用record_purchase_event。"
        "resolve_item/search_items 仅查询已有商品；404/not_found 或空列表不阻止新购买记账，"
        "普通购买应继续独立record_purchase；高级完整DTO则在payload.items填商品name，省略未知item_id，不编造ID。"
        "按ID的消耗、纠正或维护需明确已有item_id；按名称库存动作由 wubu_inventory_event 在后端同事务解析并写入。"
        "409 歧义需要明确 item_id，不自行选物品。consume 的 quantity 是消耗量，adjust 的 quantity 是实际剩余。"
        "高级record_purchase_event支持CONSUMABLE/DURABLE/UNTRACKED，耐用品每行quantity=1；包装规格单独填spec。"
        "金额是 CNY 元，两位小数；Item.unit_price_cents 是分；时间是带时区 RFC3339。"
        "写入必须稳定保存 idempotency_key，同一现实事件重试复用原键和原参数；结果未知不宣称成功；409 不换键重发。"
        "查询成功不等于记账成功；只有购买写入成功后才能告诉用户已记账。"
        "使用运行时提供的工具调用协议和合法 JSON 参数，不在普通回复中伪造工具调用。"
        "改单/删除先get_purchase_event读取updated_at，传expected_updated_at；改单保留source、external_id、原行id/item_id，"
        "不拆成改库存和改费用，重试不自动更新版本。"
        "仅根据用户记录/查询意图调用，普通聊天不自动记账。"
    )
    input_model = WubuInput

    def __init__(self, client=None):
        self.client = client or WubuClient(autostart=True)

    def permission_for(self, arguments):
        return PermissionLevel.READ if read_only_operation(arguments) else PermissionLevel.WRITE

    def side_effects_for(self, arguments):
        return frozenset({SideEffect.NONE if self.permission_for(arguments) is PermissionLevel.READ else SideEffect.LOCAL_STATE})

    def safe_to_replay(self, arguments):
        spec = CONTRACT[arguments["operation"]]
        return read_only_operation(arguments) or (spec["idempotent"] and bool(arguments.get("idempotency_key")))

    def resource_scope(self, arguments):
        return f"wubu:{arguments['operation']}:{arguments.get('item_id') or arguments.get('purchase_id') or arguments.get('account_id') or 'collection'}"

    def confirmation_description(self, arguments):
        return f"在物簿执行 {arguments['operation']}"

    async def execute(self, arguments: WubuInput):
        spec = CONTRACT[arguments.operation]
        values = arguments.model_dump()
        read_only = read_only_operation(values)
        identifier = getattr(arguments, path_id_field(arguments.operation))
        path = spec["path"].replace("{id}", quote(identifier or "", safe=""))
        query = dict(arguments.query)
        if arguments.operation == "get_inventory_history" and arguments.item_id:
            path = "/api/v1/items/" + quote(arguments.item_id, safe="") + "/inventory-events"
            if "item_id" in query:
                return ToolResult(success=False, content="请只提供一个库存历史 item_id。", error="validation_error")
        return await perform(self.client, spec["method"], path, operation=arguments.operation,
                             query=query, payload=arguments.payload if spec["method"] != "GET" else None,
                             key=arguments.idempotency_key, read_only=read_only,
                             safe_to_replay=self.safe_to_replay(values))
