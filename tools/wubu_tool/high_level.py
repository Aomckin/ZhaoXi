"""Small everyday tools; Wubu owns matching, defaults and the full transaction."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from zhaoxi.sdk import PermissionLevel, SideEffect, Tool

from tools.wubu_tool.client import WubuClient
from tools.wubu_tool.zhaoxi_notes import ZHAOXI_NOTES
from tools.wubu_tool.results import perform
from tools.wubu_tool.tool import CONTRACT


StableKey = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[\x21-\x7e]+$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Unit = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


def compact_optional_schema(schema):
    """Optional values are omitted rather than advertised as nullable unions."""
    def simplify(value):
        if isinstance(value, dict):
            variants = value.get("anyOf")
            if variants and len(variants) == 2 and {v.get("type") for v in variants} & {"null"}:
                choice = next(v for v in variants if v.get("type") != "null")
                value.pop("anyOf")
                value.update(choice)
            if value.get("default", "absent") is None:
                value.pop("default")
            for nested in value.values():
                simplify(nested)
        elif isinstance(value, list):
            for nested in value:
                simplify(nested)
    simplify(schema)


class SimpleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra=compact_optional_schema)


class PurchaseItem(SimpleInput):
    name: Name = Field(description="商品基础名称，例如无糖可乐；规格单独填 spec。")
    quantity: float = Field(gt=0, le=1_000_000_000, multiple_of=0.001, allow_inf_nan=False,
                            description="买了多少库存单位，例如一瓶填 1；2L 是规格，不是数量。")
    unit: Unit = Field(description="库存计数单位，例如瓶、包、个；一瓶2L饮料填瓶。")
    price: float | None = Field(default=None, ge=0, le=10_000_000, multiple_of=0.01, allow_inf_nan=False,
                                description="每库存单位的单价，CNY 元；不知道则省略。")
    spec: str = Field(default="", max_length=100, description="每包装规格，例如 2L、900ml，不与 name 拼接。")
    item_type: Literal["CONSUMABLE", "DURABLE", "UNTRACKED"] | None = None
    location: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def durable_quantity(self):
        if self.item_type == "DURABLE" and self.quantity != 1:
            raise ValueError("耐用品每件单独一行，quantity=1。")
        return self


class PurchaseInput(SimpleInput):
    account_id: str | None = Field(default=None, max_length=200, description="账户ID或精确名称；省略使用默认付款账户，不猜付款方式。")
    items: list[PurchaseItem] = Field(min_length=1, max_length=500)
    total: float | None = Field(default=None, ge=0, le=10_000_000_000, multiple_of=0.01, allow_inf_nan=False,
                                description="实际付款元，选填；省略由明细合计，单商品省略 price 时可由 total 推导。")
    merchant: str = Field(default="", max_length=200)
    payment_method: str = Field(default="", max_length=100)
    note: str = Field(default="", max_length=2000)


class RecordPurchaseInput(PurchaseInput):
    idempotency_key: StableKey = Field(description="每个现实事件稳定保存一个键，重试复用原键及原参数。")


class InventoryInput(SimpleInput):
    action: Literal["consume", "adjust", "open", "finish", "discard"]
    name: Name = Field(description="已有物品的名称或别名，不先查找或创建商品。")
    quantity: float | None = Field(default=None, ge=0, le=1_000_000_000, multiple_of=0.001, allow_inf_nan=False,
                                   description="consume=用掉量（正数），adjust=实际剩余；其他动作省略。")
    spec: str = Field(default="", max_length=100, description="已知包装规格；名称有多个规格时先询问。")
    note: str = Field(default="", max_length=2000)
    idempotency_key: StableKey

    @model_validator(mode="after")
    def quantity_for_action(self):
        if self.action in {"consume", "adjust"}:
            if self.quantity is None or (self.action == "consume" and self.quantity <= 0):
                raise ValueError("consume 必须填写正消耗量；adjust 必须填写实际剩余量，可为0。")
        elif self.quantity is not None:
            raise ValueError("open/finish/discard 不填 quantity。")
        return self


class SimpleWubuTool(Tool):
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})

    def __init__(self, client=None):
        self.client = client or WubuClient(autostart=True)

    def safe_to_replay(self, arguments):
        return bool(arguments.get("idempotency_key"))

    def resource_scope(self, arguments):
        return f"wubu:{self.name}"


class RecordPurchaseTool(SimpleWubuTool):
    name = "record_purchase"
    aliases = ("物簿购买记账",)
    intents = ("记录购买", "买东西记账", "记录超市购物")
    description = ZHAOXI_NOTES + (
        "把一次现实购买记入物簿。只填 items 和稳定 idempotency_key，无需 operation/payload、先查询或创建商品。"
        "一瓶2L无糖可乐5.5元：name=无糖可乐,spec=2L,quantity=1,unit=瓶,price=5.5。"
        "后端在同一事务匹配或创建商品、记录费用与库存，并默认时间/CNY/source=agent。"
        "已知付款填 price 或 total；全未知时后端金额默认0，应向用户说明未确认金额。"
        "只在用户有购买记账意图时调用；歧义向用户确认，不随意选；只有成功写入后才能说已记账。"
        "根据返回的 purchase_id、expense_amount、库存快照和 warnings 确认；金额或规格警告需请用户核对。"
        "超时结果未知，不换键或盲目重试。耐用品填item_type=DURABLE且quantity=1，服务填UNTRACKED；复杂完整DTO用高级wubu。"
    )
    input_model = RecordPurchaseInput

    async def execute(self, arguments):
        spec = CONTRACT["record_purchase"]
        return await perform(self.client, spec["method"], spec["path"], operation=self.name,
                             payload=arguments.model_dump(exclude={"idempotency_key"}, exclude_none=True),
                             key=arguments.idempotency_key, safe_to_replay=self.safe_to_replay(arguments.model_dump()))


class ValidatePurchaseTool(SimpleWubuTool):
    name = "validate_purchase"
    permission = PermissionLevel.READ
    side_effects = frozenset({SideEffect.NONE})
    description = ZHAOXI_NOTES + (
        "预检查购买的名称/规格、金额和预计库存，不写物品、购买、费用、库存或幂等记录。"
        "参数与 record_purchase 相同但不需幂等键，只有 items 必填。"
        "用于有疑问的账单；返回 warnings 时请用户核对。预检查通过不代表已记账，正式购买用 record_purchase。"
    )
    input_model = PurchaseInput

    def safe_to_replay(self, arguments):
        return True

    async def execute(self, arguments):
        spec = CONTRACT["validate_purchase"]
        return await perform(self.client, spec["method"], spec["path"], operation=self.name,
                             payload=arguments.model_dump(exclude_none=True), read_only=True, safe_to_replay=True)


class InventoryEventTool(SimpleWubuTool):
    name = "wubu_inventory_event"
    aliases = ("物簿库存事件",)
    intents = ("消耗物品", "纠正库存", "记录开封", "记录用完", "丢弃物品")
    description = ZHAOXI_NOTES + (
        "按名称/规格/别名在同一后端事务处理已有库存，不拆成先查再写。"
        "action=consume 用掉多少、adjust 实际剩多少（可0）、open 开封、finish 用完、discard 丢弃；"
        "后三项不填 quantity。spec 是包装规格，与库存数量分开。"
        "不存在不创建；ITEM_AMBIGUOUS 要询问用户规格，或选候选ID后使用高级wubu的ID操作，不偷偷选一个。"
        "写入 source=agent，幂等键稳定保存，超时不换键重发。购买记账用 record_purchase。"
    )
    input_model = InventoryInput

    async def execute(self, arguments):
        spec = CONTRACT[f"{arguments.action}_by_name"]
        payload = arguments.model_dump(exclude={"action", "idempotency_key"}, exclude_none=True)
        payload["source"] = "agent"
        return await perform(self.client, spec["method"], spec["path"], operation=f"{self.name}:{arguments.action}",
                             payload=payload, key=arguments.idempotency_key,
                             safe_to_replay=self.safe_to_replay(arguments.model_dump()))
