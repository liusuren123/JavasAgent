# -*- coding: utf-8 -*-
"""安全条件表达式求值器。

解析 YAML 技能中的 when 条件表达式，支持比较运算、字符串包含和逻辑运算。
**绝不使用 eval()**——自实现 tokenizer + 递归下降解析器。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from loguru import logger


# ======================================================================
# Token 定义
# ======================================================================

class TokenType(Enum):
    """词法分析器的 token 类型。"""
    STRING = auto()      # "hello"
    NUMBER = auto()      # 42, 3.14
    BOOLEAN = auto()     # true, false
    VARIABLE = auto()    # parameters.filename
    OP_EQ = auto()       # ==
    OP_NEQ = auto()      # !=
    OP_GT = auto()       # >
    OP_LT = auto()       # <
    OP_GTE = auto()      # >=
    OP_LTE = auto()      # <=
    OP_IN = auto()       # in
    AND = auto()         # and
    OR = auto()          # or
    NOT = auto()         # not
    LPAREN = auto()      # (
    RPAREN = auto()      # )
    EOF = auto()


@dataclass
class Token:
    """词法 token。"""
    type: TokenType
    value: str | float | int | bool
    pos: int = 0


# ======================================================================
# 词法分析器
# ======================================================================

# 两字符运算符优先匹配
_TWO_CHAR_OPS = {
    "==": TokenType.OP_EQ,
    "!=": TokenType.OP_NEQ,
    ">=": TokenType.OP_GTE,
    "<=": TokenType.OP_LTE,
}
_ONE_CHAR_OPS = {
    ">": TokenType.OP_GT,
    "<": TokenType.OP_LT,
    "(": TokenType.LPAREN,
    ")": TokenType.RPAREN,
}
_KEYWORDS = {
    "and": TokenType.AND,
    "or": TokenType.OR,
    "not": TokenType.NOT,
    "true": TokenType.BOOLEAN,
    "false": TokenType.BOOLEAN,
    "in": TokenType.OP_IN,
}


def tokenize(expr: str) -> list[Token]:
    """将表达式字符串拆分为 token 列表。

    Args:
        expr: 条件表达式字符串。

    Returns:
        token 列表。
    """
    tokens: list[Token] = []
    i = 0
    n = len(expr)

    while i < n:
        # 跳过空白
        if expr[i].isspace():
            i += 1
            continue

        # 字符串字面量 "..."
        if expr[i] == '"':
            j = i + 1
            while j < n and expr[j] != '"':
                j += 1
            tokens.append(Token(TokenType.STRING, expr[i + 1 : j], i))
            i = j + 1
            continue

        # 数字字面量
        if expr[i].isdigit() or (expr[i] == "-" and i + 1 < n and expr[i + 1].isdigit()):
            j = i + 1 if expr[i] == "-" else i
            while j < n and (expr[j].isdigit() or expr[j] == "."):
                j += 1
            num_str = expr[i:j]
            value: float | int = float(num_str) if "." in num_str else int(num_str)
            tokens.append(Token(TokenType.NUMBER, value, i))
            i = j
            continue

        # 两字符运算符
        if i + 1 < n and expr[i : i + 2] in _TWO_CHAR_OPS:
            tokens.append(Token(_TWO_CHAR_OPS[expr[i : i + 2]], expr[i : i + 2], i))
            i += 2
            continue

        # 单字符运算符
        if expr[i] in _ONE_CHAR_OPS:
            tokens.append(Token(_ONE_CHAR_OPS[expr[i]], expr[i], i))
            i += 1
            continue

        # 标识符 / 关键字 / 变量路径
        if expr[i].isalpha() or expr[i] == "_":
            j = i
            while j < n and (expr[j].isalnum() or expr[j] in "_."):
                j += 1
            word = expr[i:j]
            # 判断是否包含点号 → 变量路径
            if "." in word and word not in _KEYWORDS:
                tokens.append(Token(TokenType.VARIABLE, word, i))
            elif word in _KEYWORDS:
                tt = _KEYWORDS[word]
                val = word  # 默认
                if tt == TokenType.BOOLEAN:
                    val = word == "true"
                tokens.append(Token(tt, val, i))
            else:
                # 纯标识符也当作变量
                tokens.append(Token(TokenType.VARIABLE, word, i))
            i = j
            continue

        # 未知字符 → 跳过
        logger.warning("表达式求值器：跳过未知字符 '{}' @ {}", expr[i], i)
        i += 1

    tokens.append(Token(TokenType.EOF, None, i))
    return tokens


# ======================================================================
# AST 节点
# ======================================================================

@dataclass
class ASTNode:
    """抽象语法树节点基类。"""
    pass


@dataclass
class LiteralNode(ASTNode):
    """字面量节点（字符串、数字、布尔）。"""
    value: Any


@dataclass
class VariableNode(ASTNode):
    """变量引用节点。"""
    name: str


@dataclass
class CompareNode(ASTNode):
    """比较运算节点。"""
    op: str
    left: ASTNode
    right: ASTNode


@dataclass
class InNode(ASTNode):
    """字符串包含节点（"xxx" in variable）。"""
    needle: ASTNode
    haystack: ASTNode


@dataclass
class LogicNode(ASTNode):
    """逻辑运算节点（and / or）。"""
    op: str
    left: ASTNode
    right: ASTNode


@dataclass
class NotNode(ASTNode):
    """逻辑非节点。"""
    operand: ASTNode


# ======================================================================
# 递归下降解析器
# ======================================================================

class _Parser:
    """递归下降表达式解析器。

    文法（优先级从低到高）：
        expr    → or_expr
        or_expr → and_expr ("or" and_expr)*
        and_expr→ not_expr ("and" not_expr)*
        not_expr→ "not" not_expr | cmp_expr
        cmp_expr→ primary (("==" | "!=" | ">" | "<" | ">=" | "<=" | "in") primary)?
        primary → STRING | NUMBER | BOOLEAN | VARIABLE | "(" expr ")"
    """

    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    def parse(self) -> ASTNode | None:
        """解析整个表达式为 AST。"""
        try:
            node = self._or_expr()
            if self._current().type != TokenType.EOF:
                return None
            return node
        except Exception:
            return None

    # ---------- 语法规则 ----------

    def _or_expr(self) -> ASTNode:
        left = self._and_expr()
        while self._current().type == TokenType.OR:
            self._advance()
            right = self._and_expr()
            left = LogicNode("or", left, right)
        return left

    def _and_expr(self) -> ASTNode:
        left = self._not_expr()
        while self._current().type == TokenType.AND:
            self._advance()
            right = self._not_expr()
            left = LogicNode("and", left, right)
        return left

    def _not_expr(self) -> ASTNode:
        if self._current().type == TokenType.NOT:
            self._advance()
            operand = self._not_expr()
            return NotNode(operand)
        return self._cmp_expr()

    def _cmp_expr(self) -> ASTNode:
        left = self._primary()

        cmp_tokens = {
            TokenType.OP_EQ: "==",
            TokenType.OP_NEQ: "!=",
            TokenType.OP_GT: ">",
            TokenType.OP_LT: "<",
            TokenType.OP_GTE: ">=",
            TokenType.OP_LTE: "<=",
        }

        tt = self._current().type
        if tt in cmp_tokens:
            op = cmp_tokens[tt]
            self._advance()
            right = self._primary()
            return CompareNode(op, left, right)

        if tt == TokenType.OP_IN:
            self._advance()
            right = self._primary()
            return InNode(left, right)

        return left

    def _primary(self) -> ASTNode:
        tok = self._current()

        if tok.type == TokenType.STRING:
            self._advance()
            return LiteralNode(tok.value)

        if tok.type == TokenType.NUMBER:
            self._advance()
            return LiteralNode(tok.value)

        if tok.type == TokenType.BOOLEAN:
            self._advance()
            return LiteralNode(tok.value)

        if tok.type == TokenType.VARIABLE:
            self._advance()
            return VariableNode(tok.value)

        if tok.type == TokenType.LPAREN:
            self._advance()
            node = self._or_expr()
            if self._current().type == TokenType.RPAREN:
                self._advance()
            return node

        # 意外 token → 返回 False 字面量
        self._advance()
        return LiteralNode(False)

    # ---------- 工具方法 ----------

    def _current(self) -> Token:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else Token(TokenType.EOF, None)

    def _advance(self) -> None:
        self._pos += 1


# ======================================================================
# 求值器
# ======================================================================

class ExpressionEvaluator:
    """安全条件表达式求值器。

    不使用 eval()，通过 tokenizer + recursive descent parser 解析表达式。
    语法错误或变量缺失时返回 False 而非抛异常。
    """

    def evaluate(self, expr: str, context: Any) -> bool:
        """求值条件表达式。

        Args:
            expr: 条件表达式字符串，如 ``parameters.name == "test"``。
            context: SkillContext 实例（需支持 get(key) 方法）。

        Returns:
            布尔结果。语法错误时返回 False。
        """
        if not expr or not isinstance(expr, str):
            return False

        try:
            tokens = tokenize(expr)
            parser = _Parser(tokens)
            ast = parser.parse()
            if ast is None:
                logger.warning("表达式语法错误: {}", expr)
                return False
            return self._eval_node(ast, context)
        except Exception as e:
            logger.warning("表达式求值异常: {} — {}", expr, e)
            return False

    def _eval_node(self, node: ASTNode, context: Any) -> bool:
        """递归求值 AST 节点。"""
        if isinstance(node, LiteralNode):
            return bool(node.value)

        if isinstance(node, VariableNode):
            val = context.get(node.name)
            return bool(val) if val is not None else False

        if isinstance(node, CompareNode):
            left = self._resolve_value(node.left, context)
            right = self._resolve_value(node.right, context)
            return self._compare(node.op, left, right)

        if isinstance(node, InNode):
            needle = self._resolve_value(node.needle, context)
            haystack = self._resolve_value(node.haystack, context)
            if isinstance(haystack, str) and isinstance(needle, str):
                return needle in haystack
            return False

        if isinstance(node, LogicNode):
            left = self._eval_node(node.left, context)
            if node.op == "or":
                return left or self._eval_node(node.right, context)
            # and
            return left and self._eval_node(node.right, context)

        if isinstance(node, NotNode):
            return not self._eval_node(node.operand, context)

        return False

    def _resolve_value(self, node: ASTNode, context: Any) -> Any:
        """解析节点为 Python 值。"""
        if isinstance(node, LiteralNode):
            return node.value
        if isinstance(node, VariableNode):
            return context.get(node.name)
        return None

    @staticmethod
    def _compare(op: str, left: Any, right: Any) -> bool:
        """执行比较运算。"""
        try:
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            if op == ">":
                return left > right  # type: ignore
            if op == "<":
                return left < right  # type: ignore
            if op == ">=":
                return left >= right  # type: ignore
            if op == "<=":
                return left <= right  # type: ignore
        except TypeError:
            return False
        return False
