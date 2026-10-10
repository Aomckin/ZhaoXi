"""Shared result handling: keep service facts, errors and warnings intact."""
import asyncio
from decimal import Decimal

from zhaoxi.sdk import ToolResult
from tools.wubu_tool.client import WubuError


def number(value):
    return format(Decimal(str(value)), "f").rstrip("0").rstrip(".") if "." in str(value) else str(value)


def purchase_confirmation(data, *, preview=False):
    """Use committed response snapshots; never requery inventory to confirm a write."""
    if not isinstance(data, dict) or "expense_amount" not in data:
        return "物簿已返回预检查结果，未写入。" if preview else "已在物簿记录，请查看返回数据。"
    rows = []
    for item in data.get("items", []):
        name = " ".join(str(item.get(k) or "") for k in ("name", "spec")).strip()
        unit = item.get("unit", "")
        row = f"{name} × {number(item.get('quantity_added', item.get('quantity', 0)))}{unit}"
        if item.get("inventory_after") is not None:
            row += f"，{'预计库存' if preview else '当前库存'} {number(item['inventory_after'])}{unit}"
        rows.append(row)
    prefix = "购买预检查（未写入）" if preview else "已记录购买"
    content = prefix + "：" + "；".join(rows) + f"。{'预计支出' if preview else '实际支出'} ¥{Decimal(str(data['expense_amount'])):.2f}。"
    if data.get("purchase_id"):
        content += f"购买记录：{data['purchase_id']}。"
    if data.get("validation_status"):
        content += f"校验状态：{data['validation_status']}。"
    for warning in data.get("warnings", []):
        if not isinstance(warning, dict):
            content += f"请核对警告：{warning}。"
            continue
        code = warning.get("code", "WARNING")
        explanation = {
            "PURCHASE_AMOUNT_INCONSISTENT": "请核对实际付款与数量、单价及小计是否一致",
            "SPEC_QUANTITY_CONFLICT": "请核对是否将包装规格误填成购买数量或库存单位",
        }.get(code, "请核对此警告")
        content += f"警告 {code}：{explanation}；{warning.get('message', '')}。"
    return content


def error_content(exc):
    content = str(exc)
    error = exc.data.get("error", {}) if isinstance(exc.data, dict) else {}
    if not isinstance(error, dict):
        return content
    if exc.code == "ITEM_AMBIGUOUS":
        content += " 物品有歧义，请询问用户规格或候选 ID，不随意选择。"
        for candidate in error.get("candidates", []):
            content += (f" 候选：{candidate.get('name', '')} {candidate.get('spec', '')}，"
                        f"库存 {candidate.get('current_quantity', '')}{candidate.get('unit', '')}，"
                        f"id={candidate.get('id', '')}。")
    elif exc.code in {"ITEM_NOT_FOUND", "not_found"}:
        content += " 未找到已有物品；若是首次购买用 record_purchase，消耗等库存操作需先核实名称/规格。"
    if exc.code == "ACCOUNT_MERCHANT_MISMATCH":
        content += " 消费账户绑定商家与本次商家不匹配；请核对商家或选择匹配账户，不静默换账户扣款。"
    if error.get("suggested_action"):
        content += f" 建议：{error['suggested_action']}。"
    return content


async def perform(client, method, path, *, operation, query=None, payload=None, key=None,
                  read_only=False, safe_to_replay=False):
    metadata = {"fact_source": "wubu", "operation": operation,
                "safe_to_replay": safe_to_replay, "unknown_outcome": False}
    try:
        data, replayed = await asyncio.to_thread(client.request, method, path, query, payload, key,
                                                read_only=read_only)
    except WubuError as exc:
        metadata.update(unknown_outcome=exc.unknown, retryable=exc.retryable, http_status=exc.status)
        if not read_only:
            metadata["retry_instruction"] = "重试只能复用原版本、原 idempotency_key 和完全相同的参数；409 不自动换键。"
        return ToolResult(success=False, content=error_content(exc), error=exc.code, data=exc.data, metadata=metadata)
    metadata["idempotency_replayed"] = replayed
    if operation in {"record_purchase", "record_purchase_event", "amend_purchase_event", "validate_purchase"}:
        content = purchase_confirmation(data, preview=read_only)
        if read_only:
            metadata["written"] = False
    elif operation == "delete_purchase_event":
        content = "已在物簿撤销购买记录及其费用、库存贡献；原历史保留。"
    elif operation == "get_balance" and isinstance(data, dict) and "liquid_balance" in data:
        content = (f"自由可用资金 ¥{Decimal(str(data['liquid_balance'])):.2f}；"
                   f"受限消费储值 ¥{Decimal(str(data['consumption_balance'])):.2f}。"
                   "消费储值不能当作自由现金；total_balance含信用卡和停用账户净额。")
    elif operation == "get_account_statistics" and isinstance(data, dict) and "top_up_principal" in data:
        content = "账户统计：" + "；".join(f"{label} ¥{Decimal(str(data.get(field, 0))):.2f}" for field,label in [
            ("top_up_principal","充值本金"),("bonus","赠送"),("expense","消费"),("refund","退款"),
            ("net_expense","净消费"),("current_balance","当前余额")]) + f"；赠送比例 {data.get('bonus_ratio', 0)}。"
    elif isinstance(data, dict) and isinstance(data.get("transactions"), list):
        content = ("已读取资金事件：" if read_only else "已记录资金事件：") + "；".join(
            f"{tx.get('type')} ¥{Decimal(str(tx.get('amount',0))):.2f}，账户 {tx.get('account_id')}，"
            f"余额 {tx.get('balance_before')}→{tx.get('balance_after')}" for tx in data["transactions"]) + "。"
        if operation in {"top_up_account", "record_bonus"}:
            content += "充值本金转账和赠送储值不计普通收入或消费。"
    else:
        content = "已从物簿读取事实。" if read_only else "已在物簿记录。"
    if isinstance(data, dict) and operation not in {"record_purchase", "record_purchase_event", "amend_purchase_event", "validate_purchase"}:
        for warning in data.get("warnings") or []:
            code = warning.get("code", "WARNING")
            note = {"TOP_UP_VALUE_LOSS": "到账低于实付，请核对损失差额；不计普通消费",
                    "ACCOUNT_HAS_REMAINING_BALANCE": "停用账户仍有余额，请核对受限储值；记录和余额保留"}.get(code, "请核对")
            content += f"警告 {code}：{note}；{warning.get('message','')}。"
    return ToolResult(success=True, content=content, data=data, metadata=metadata)
