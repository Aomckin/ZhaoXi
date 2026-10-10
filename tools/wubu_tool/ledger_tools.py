"""Flat public tools generated from the locally pinned Wubu contract."""
from copy import deepcopy
from typing import Any, ClassVar, Literal
from urllib.parse import quote

from pydantic import Field, create_model, model_validator
from zhaoxi.sdk import PermissionLevel, SideEffect
from tools.wubu_tool.high_level import SimpleInput, SimpleWubuTool, StableKey
from tools.wubu_tool.zhaoxi_notes import ZHAOXI_NOTES
from tools.wubu_tool.results import perform
from tools.wubu_tool.tool import CONTRACT, path_id_field

NOTES = {
    "create_account": "创建真实账户；initial_balance是当前真实余额，信用卡用净余额。account_class=STORAGE自由资金/CONSUMPTION消费储值；会员用MERCHANT_BALANCE，可绑定merchant。不猜旧费用付款账户。",
    "update_account": "编辑账户名称、启用状态、分类或商家；只改当前分类，不重写历史。停用消费余额提示ACCOUNT_HAS_REMAINING_BALANCE，仍需核对剩余余额；停用默认账户前更换默认。",
    "get_accounts": "查询账户，可筛account_class、merchant、active。",
    "get_account": "读取明确账户ID的当前账户事实。",
    "get_account_statistics": "账户充值本金、赠送、消费、退款、净消费、当前余额、bonus_ratio。跨账户退款仍归原消费账户统计。",
    "get_money_settings": "读取默认付款账户。",
    "set_default_payment_account": "设置明确账户ID或精确名称为默认付款账户，不自动推断付款来源。",
    "get_balance": "自由可用资金liquid_balance与受限消费储值consumption_balance必须分开解释；available_balance仅自由资金别名。total_value相加不等于自由现金，total_balance含信用卡/停用账户。",
    "record_income": "记录普通收入，amount为CNY元。赠送储值用record_bonus，售出耐用品用sell_item，不拆成多笔。",
    "record_expense": "记录不影响物品库存的普通支出，明确付款账户或使用默认。购买商品用record_purchase。绑定商家冲突需核对账户/merchant。",
    "transfer_money": "同一事务转账，from_account和to_account为账户ID或精确名称；不计收入和消费。",
    "top_up_account": "一次原子充值：paid_amount实付，credited_amount到账；100送10产生本金转出100、转入100、BONUS10，不算普通收入消费。只转入消费账户；少到账返回TOP_UP_VALUE_LOSS，请核对，不偷偷补差。",
    "record_bonus": "给CONSUMPTION消费账户记录正赠送储值，不计普通收入，不能加到STORAGE自由资金账户。",
    "record_refund": "关联原EXPENSE或purchase_event_id退款，默认回原账户，也可明确account_id退到其他账户。仅明确实际退货时传return_items；不单独调整库存或收入。",
    "adjust_balance": "记录真实绝对余额actual_balance，支持负净余额；不是增加量。reason说明原因，不计普通收支。",
    "reconcile_account": "核对真实绝对余额actual_balance并由后端记录差额；不把差额记为消费或收入。",
    "add_maintenance": "维护和账户扣款在一次事务完成；明确item_id，title与cost，PLANNED必须cost=0。",
    "sell_item": "一次后端原子售出耐用品并入账收入；amount售出元，account_id收款账户。SOLD终态，不另调用record_income。",
    "retire_item": "退休/弃置耐用品，RETIRED终态；不通过手改库存绕过生命周期。",
    "move_item": "移动耐用品到明确location，记录生命周期位置事件。",
    "set_durable_status": "设置ACTIVE在用/STORED收纳/LOST丢失；找到用ACTIVE。STORED仍拥有1件，LOST库存0。售出/退休必须用sell_item/retire_item。",
    "get_recent_transactions": "查询资金事件，type可筛BONUS；period为上海日历，不能与from/to混用。",
    "get_money_summary": "读取后端资金汇总；赠送不算普通收入，转账/调整不算收支。",
    "get_expense_summary": "读取支出、退款和净支出；跨月退款可能产生负净支出。",
    "get_income_summary": "读取普通收入，BONUS消费赠送不当作收入。",
    "get_category_summary": "按分类读取后端资金汇总。",
    "get_merchant_summary": "按商家读取后端资金汇总。",
    "get_money_categories": "查询资金分类。",
    "save_money_category": "创建或编辑资金分类，保留既有分类标识，不重写历史事件。",
    "get_durable_items": "查询耐用品，按状态/位置筛选；SOLD和RETIRED为终态。",
    "get_durable_history": "读取物品生命周期历史。",
    "get_item_total_cost": "读取后端购买/维护/退款/售出与持有成本；不自行拼凑库存价格估算。",
    "get_recent_maintenance": "查询最近维护记录。",
}

OPERATIONS = {name: ("add_maintenance_event" if name == "add_maintenance" else name) for name in NOTES}


class ContractInput(SimpleInput):
    operation_name: ClassVar[str] = ""

    @model_validator(mode="after")
    def check_semantics(self):
        values = self.model_dump(exclude_none=True)
        if self.operation_name == "record_refund" and not (values.get("purchase_event_id") or values.get("related_transaction_id")):
            raise ValueError("退款必须关联原购买事件或原支出流水，不能猜。")
        if values.get("period") and (values.get("from") or values.get("to")):
            raise ValueError("period不能与from/to混用。")
        if self.operation_name == "update_account" and not (set(values) - {"account_id", "idempotency_key"}):
            raise ValueError("编辑账户至少提供一个变更字段。")
        if self.operation_name == "add_maintenance" and values.get("status") == "PLANNED" and values.get("cost", 0):
            raise ValueError("PLANNED维护cost必须为0。")
        if self.operation_name in {"transfer_money", "top_up_account"} and values.get("from_account") == values.get("to_account"):
            raise ValueError("转出和转入不能是同一账户。")
        for field in ("account_id", "item_id"):
            if values.get(field) in {".", ".."}:
                raise ValueError("路径ID无效。")
        return self


def field_type(name, schema):
    """Use pydantic's normal validation, including nested return_items."""
    if "enum" in schema:
        return Literal[tuple(schema["enum"])]
    kind = schema.get("type", "string")
    if isinstance(kind, list):
        kind = next(t for t in kind if t != "null")
    if kind == "array":
        return list[field_type(name + "Row", schema["items"])]
    if kind == "object":
        return model_for(name + "Object", schema, SimpleInput)
    return {"string": str, "number": float, "integer": int, "boolean": bool}.get(kind, Any)


def model_for(name, schema, base=ContractInput, extra_required=()):
    required = set(schema.get("required", [])) | set(extra_required)
    fields = {}
    for key, spec in schema.get("properties", {}).items():
        if key in {"source", "currency"}:
            continue
        kind = field_type(name + key.title(), spec)
        options = {"description": spec.get("description", "")}
        for schema_key, option in [("minLength", "min_length"), ("maxLength", "max_length"),
                                  ("minimum", "ge"), ("maximum", "le"), ("exclusiveMinimum", "gt"),
                                  ("multipleOf", "multiple_of"), ("pattern", "pattern"),
                                  ("minItems", "min_length"), ("maxItems", "max_length")]:
            if schema_key in spec:
                options[option] = spec[schema_key]
        if kind is float:
            options.update(allow_inf_nan=False, strict=True)
        if kind is str:
            options["min_length"] = max(options.get("min_length", 0), 1 if key in required else 0)
        if key in required:
            fields[key] = (kind, Field(**options))
        else:
            fields[key] = (kind | None, Field(default=None, **options))
    return create_model(name, __base__=base, **fields)


class ContractTool(SimpleWubuTool):
    operation: str

    async def execute(self, arguments):
        spec = CONTRACT[self.operation]
        values = arguments.model_dump(exclude_none=True)
        key = values.pop("idempotency_key", None)
        path = spec["path"]
        if "{id}" in path:
            identifier = values.pop(path_id_field(self.operation))
            path = path.replace("{id}", quote(identifier, safe=""))
        read = spec["method"] == "GET"
        if not read and "source" in spec["payload"].get("properties", {}):
            values["source"] = "agent"
        return await perform(self.client, spec["method"], path, operation=self.name,
                             query=values if read else None, payload=None if read else values,
                             key=key, read_only=read, safe_to_replay=self.safe_to_replay(arguments.model_dump()))

    def safe_to_replay(self, arguments):
        spec = CONTRACT[self.operation]
        return spec["method"] == "GET" or (spec["idempotent"] and bool(arguments.get("idempotency_key")))


def create_ledger_tools(client):
    tools = []
    for name, operation in OPERATIONS.items():
        spec = CONTRACT[operation]
        read = spec["method"] == "GET"
        schema = deepcopy(spec["query"] if read else spec["payload"])
        required = list(schema.get("required", []))
        if "{id}" in spec["path"]:
            identifier = path_id_field(operation)
            schema.setdefault("properties", {})[identifier] = {"type": "string", "minLength": 1, "maxLength": 200,
                                                              "description": "明确ID，按路径编码；名称查询先用对应列表。"}
            required.append(identifier)
        if not read:
            schema.setdefault("properties", {})["idempotency_key"] = {"type": "string", "minLength": 1, "maxLength": 200,
                "pattern": r"^[\x21-\x7e]+$", "description": "同一现实事件稳定保存原键；重试不换键或改变参数。"}
            required.append("idempotency_key")
        required += {"sell_item": ["amount"], "move_item": ["location"],
                     "set_durable_status": ["status"]}.get(name, [])
        if name == "set_durable_status":
            schema["properties"]["status"]["enum"] = ["ACTIVE", "STORED", "LOST"]
        model = model_for(name.title().replace("_", "") + "Input", schema, extra_required=required)
        model.operation_name = name
        cls = type(name.title().replace("_", "") + "Tool", (ContractTool,), {
            "name": name, "operation": operation, "input_model": model,
            "description": ZHAOXI_NOTES + NOTES[name] + ("" if read else "写入保持朝汐确认策略，稳定幂等键；超时/重置结果未知不盲重试。"),
            "permission": PermissionLevel.READ if read else PermissionLevel.WRITE,
            "side_effects": frozenset({SideEffect.NONE if read else SideEffect.LOCAL_STATE}),
        })
        tools.append(cls(client))
    return tools
