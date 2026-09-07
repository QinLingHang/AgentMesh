from __future__ import annotations

import ast
import operator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.tools.contracts import ToolDefinition
from app.tools.registry import ToolRegistry


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _safe_calculate(expression: str) -> int | float:
    expression = str(expression or "").strip()
    if not expression:
        raise ValueError("expression is required")
    if len(expression) > 200:
        raise ValueError("expression is too long")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("invalid arithmetic expression") from exc

    def evaluate(node: ast.AST) -> int | float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)

        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("only numeric literals are allowed")
            return value

        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
            return _UNARY_OPERATORS[type(node.op)](evaluate(node.operand))

        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            left = evaluate(node.left)
            right = evaluate(node.right)

            if isinstance(node.op, ast.Pow):
                if abs(right) > 12:
                    raise ValueError("exponent is too large")
                if abs(left) > 1_000_000:
                    raise ValueError("base is too large")

            try:
                value = _BINARY_OPERATORS[type(node.op)](left, right)
            except ZeroDivisionError as exc:
                raise ValueError("division by zero") from exc

            if isinstance(value, complex) or abs(value) > 1e18:
                raise ValueError("result is outside the supported range")
            return value

        raise ValueError("unsupported expression")

    return evaluate(tree)


def _calculator(arguments: dict[str, Any]) -> dict[str, Any]:
    expression = str(arguments.get("expression", "")).strip()
    return {
        "expression": expression,
        "result": _safe_calculate(expression),
    }


def _current_time(arguments: dict[str, Any]) -> dict[str, Any]:
    timezone_name = str(arguments.get("timezone") or "UTC").strip() or "UTC"
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {timezone_name}") from exc

    now = datetime.now(timezone)
    return {
        "timezone": timezone_name,
        "iso8601": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "time": now.strftime("%H:%M:%S"),
    }


def _text_stats(arguments: dict[str, Any]) -> dict[str, Any]:
    text = str(arguments.get("text", ""))
    if len(text) > 100_000:
        raise ValueError("text is too long")

    words = [part for part in text.split() if part]
    lines = text.splitlines() or ([""] if text == "" else [text])
    return {
        "characters": len(text),
        "charactersWithoutWhitespace": sum(1 for ch in text if not ch.isspace()),
        "words": len(words),
        "lines": len(lines),
    }


def register_builtin_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="calculator",
            description="Evaluate a basic arithmetic expression exactly with a sandboxed arithmetic parser.",
            inputSchema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Arithmetic expression such as 382 * 927",
                    }
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
            riskLevel="low",
        ),
        _calculator,
    )

    registry.register(
        ToolDefinition(
            name="current_time",
            description="Get the current date and time for an IANA timezone such as Asia/Shanghai or America/New_York.",
            inputSchema={
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone name; defaults to UTC",
                    }
                },
                "additionalProperties": False,
            },
            riskLevel="low",
        ),
        _current_time,
    )

    registry.register(
        ToolDefinition(
            name="text_stats",
            description="Count characters, non-whitespace characters, words and lines in text.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
            riskLevel="low",
        ),
        _text_stats,
    )
