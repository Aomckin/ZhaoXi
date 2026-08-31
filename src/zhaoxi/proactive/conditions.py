"""Small safe condition evaluator for proactive subscriptions."""

from typing import Any


class ConditionError(ValueError):
    pass


def _resolve(path: Any, context: dict[str, Any]) -> Any:
    if not isinstance(path, str) or not path.startswith("$."):
        return path
    value: Any = context
    for part in path[2:].split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def evaluate(expression: Any, context: dict[str, Any], *, depth: int = 0) -> bool:
    if depth > 12:
        raise ConditionError("condition 嵌套过深")
    if expression is None:
        return True
    if not isinstance(expression, dict) or len(expression) != 1:
        raise ConditionError("condition 必须是单操作表达式")
    operator, operands = next(iter(expression.items()))
    if operator in {"and", "or"}:
        if not isinstance(operands, list) or not operands:
            raise ConditionError(f"{operator} 需要非空列表")
        values = [evaluate(item, context, depth=depth + 1) for item in operands]
        return all(values) if operator == "and" else any(values)
    if operator == "not":
        return not evaluate(operands, context, depth=depth + 1)
    if operator == "exists":
        return _resolve(operands, context) is not None
    if not isinstance(operands, list) or len(operands) != 2:
        raise ConditionError(f"{operator} 需要两个参数")
    left, right = (_resolve(item, context) for item in operands)
    operations = {
        "eq": lambda: left == right,
        "ne": lambda: left != right,
        "gt": lambda: left > right,
        "gte": lambda: left >= right,
        "lt": lambda: left < right,
        "lte": lambda: left <= right,
        "in": lambda: left in right,
        "contains": lambda: right in left,
    }
    if operator not in operations:
        raise ConditionError(f"不支持的 condition 操作：{operator}")
    try:
        return bool(operations[operator]())
    except (TypeError, KeyError) as exc:
        raise ConditionError(f"condition 参数类型不兼容：{operator}") from exc
