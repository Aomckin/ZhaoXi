"""Small safe expression evaluator for workflow conditions."""

from typing import Any


class WorkflowExpressionError(ValueError):
    pass


def resolve_path(context: dict[str, Any], path: str) -> Any:
    if not path.startswith("$."):
        raise WorkflowExpressionError("变量路径必须以 $. 开头")
    value: Any = context
    for part in path[2:].split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise WorkflowExpressionError(f"变量不存在：{path}")
    return value


def resolve_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$."):
        return resolve_path(context, value)
    if isinstance(value, list):
        return [resolve_value(item, context) for item in value]
    if isinstance(value, dict) and set(value) == {"value"}:
        return resolve_value(value["value"], context)
    return value


def evaluate(expression: Any, context: dict[str, Any]) -> bool:
    if not isinstance(expression, dict) or len(expression) != 1:
        raise WorkflowExpressionError("表达式必须只包含一个操作符")
    operator, operands = next(iter(expression.items()))
    if operator == "not":
        return not evaluate(operands, context)
    if operator in {"and", "or"}:
        if not isinstance(operands, list) or not operands:
            raise WorkflowExpressionError(f"{operator} 需要非空表达式列表")
        if operator == "and":
            return all(evaluate(item, context) for item in operands)
        return any(evaluate(item, context) for item in operands)
    if operator == "exists":
        try:
            return resolve_path(context, operands) is not None
        except WorkflowExpressionError:
            return False
    if operator not in {"eq", "ne", "in"} or not isinstance(operands, list) or len(operands) != 2:
        raise WorkflowExpressionError(f"不支持的表达式：{operator}")
    left, right = (resolve_value(item, context) for item in operands)
    if operator == "eq":
        return left == right
    if operator == "ne":
        return left != right
    try:
        return left in right
    except TypeError as exc:
        raise WorkflowExpressionError("in 的右操作数不可枚举") from exc
