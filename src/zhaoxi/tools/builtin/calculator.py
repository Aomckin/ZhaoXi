"""Safe arithmetic expression evaluator."""

import ast
import operator
from typing import Callable

from pydantic import BaseModel, Field

from zhaoxi.tools.base import Tool, ToolResult


class CalculatorInput(BaseModel):
    expression: str = Field(min_length=1, max_length=200, description="只含基础运算符的数学表达式")


_BINARY: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[float], float]] = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def evaluate(expression: str) -> int | float:
    """Evaluate only numbers and explicitly allowed arithmetic operators."""
    tree = ast.parse(expression, mode="eval")

    def visit(node: ast.AST, depth: int = 0) -> int | float:
        if depth > 20:
            raise ValueError("表达式嵌套过深")
        if isinstance(node, ast.Expression):
            return visit(node.body, depth + 1)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if abs(node.value) > 1e100:
                raise ValueError("数字过大")
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = visit(node.left, depth + 1), visit(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("指数过大")
            result = _BINARY[type(node.op)](left, right)
            if abs(result) > 1e100:
                raise ValueError("结果过大")
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](visit(node.operand, depth + 1))
        raise ValueError("只支持数字、括号和 + - * / % ** 运算")

    return visit(tree)


class CalculatorTool(Tool):
    name = "calculator"
    description = "安全计算包含 + - * / % ** 和括号的基础数学表达式。"
    input_model = CalculatorInput

    async def execute(self, arguments: CalculatorInput) -> ToolResult:
        try:
            value = evaluate(arguments.expression)
        except (SyntaxError, ValueError, ZeroDivisionError, OverflowError) as exc:
            return ToolResult(success=False, content="无法计算该表达式。", error=str(exc))
        return ToolResult(success=True, content=str(value), data={"result": value})

