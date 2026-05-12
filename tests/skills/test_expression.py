# -*- coding: utf-8 -*-
"""ExpressionEvaluator 测试。"""

import pytest

from src.skills.context import SkillContext
from src.skills.expression import ExpressionEvaluator


@pytest.fixture
def evaluator():
    return ExpressionEvaluator()


# ======================================================================
# 等值比较
# ======================================================================

class TestEquality:
    def test_eq_string(self, evaluator):
        ctx = SkillContext(parameters={"name": "test"})
        assert evaluator.evaluate('parameters.name == "test"', ctx) is True

    def test_eq_string_false(self, evaluator):
        ctx = SkillContext(parameters={"name": "other"})
        assert evaluator.evaluate('parameters.name == "test"', ctx) is False

    def test_neq_number(self, evaluator):
        ctx = SkillContext(parameters={"count": 0})
        assert evaluator.evaluate("parameters.count != 0", ctx) is False

    def test_neq_number_true(self, evaluator):
        ctx = SkillContext(parameters={"count": 5})
        assert evaluator.evaluate("parameters.count != 0", ctx) is True


# ======================================================================
# 大小比较
# ======================================================================

class TestComparison:
    def test_gt(self, evaluator):
        ctx = SkillContext(variables={"retries": 5})
        assert evaluator.evaluate("variables.retries > 3", ctx) is True

    def test_gt_false(self, evaluator):
        ctx = SkillContext(variables={"retries": 2})
        assert evaluator.evaluate("variables.retries > 3", ctx) is False

    def test_lt(self, evaluator):
        ctx = SkillContext(variables={"retries": 1})
        assert evaluator.evaluate("variables.retries < 3", ctx) is True

    def test_gte(self, evaluator):
        ctx = SkillContext(variables={"retries": 3})
        assert evaluator.evaluate("variables.retries >= 3", ctx) is True

    def test_lte(self, evaluator):
        ctx = SkillContext(variables={"retries": 3})
        assert evaluator.evaluate("variables.retries <= 3", ctx) is True


# ======================================================================
# 字符串包含
# ======================================================================

class TestStringIn:
    def test_in_found(self, evaluator):
        ctx = SkillContext(result={"text": "This is a PDF file"})
        assert evaluator.evaluate('"PDF" in result.text', ctx) is True

    def test_in_not_found(self, evaluator):
        ctx = SkillContext(result={"text": "This is a Word file"})
        assert evaluator.evaluate('"PDF" in result.text', ctx) is False


# ======================================================================
# 逻辑运算
# ======================================================================

class TestLogic:
    def test_and_true(self, evaluator):
        ctx = SkillContext(parameters={"a": "x", "b": 1})
        assert evaluator.evaluate('parameters.a == "x" and parameters.b > 0', ctx) is True

    def test_and_false(self, evaluator):
        ctx = SkillContext(parameters={"a": "y", "b": 1})
        assert evaluator.evaluate('parameters.a == "x" and parameters.b > 0', ctx) is False

    def test_or_true(self, evaluator):
        ctx = SkillContext(parameters={"a": "y", "b": 1})
        assert evaluator.evaluate('parameters.a == "x" or parameters.b > 0', ctx) is True

    def test_or_false(self, evaluator):
        ctx = SkillContext(parameters={"a": "y", "b": 0})
        assert evaluator.evaluate('parameters.a == "x" or parameters.b > 0', ctx) is False


# ======================================================================
# 逻辑非
# ======================================================================

class TestNot:
    def test_not_true(self, evaluator):
        ctx = SkillContext(parameters={"dry_run": True})
        assert evaluator.evaluate("not parameters.dry_run", ctx) is False

    def test_not_false(self, evaluator):
        ctx = SkillContext(parameters={"dry_run": False})
        assert evaluator.evaluate("not parameters.dry_run", ctx) is True

    def test_not_variable_missing(self, evaluator):
        ctx = SkillContext()
        assert evaluator.evaluate("not parameters.dry_run", ctx) is True


# ======================================================================
# 边界情况
# ======================================================================

class TestEdgeCases:
    def test_missing_variable_returns_false(self, evaluator):
        ctx = SkillContext()
        assert evaluator.evaluate('parameters.name == "test"', ctx) is False

    def test_syntax_error_returns_false(self, evaluator):
        ctx = SkillContext()
        assert evaluator.evaluate("!!! invalid !!!", ctx) is False

    def test_empty_expr_returns_false(self, evaluator):
        ctx = SkillContext()
        assert evaluator.evaluate("", ctx) is False

    def test_none_expr_returns_false(self, evaluator):
        ctx = SkillContext()
        assert evaluator.evaluate(None, ctx) is False  # type: ignore

    def test_nested_path(self, evaluator):
        ctx = SkillContext(parameters={"file": {"name": "test"}})
        assert evaluator.evaluate('parameters.file.name == "test"', ctx) is True

    def test_boolean_literal_true(self, evaluator):
        ctx = SkillContext(parameters={"flag": True})
        assert evaluator.evaluate("parameters.flag == true", ctx) is True

    def test_boolean_literal_false(self, evaluator):
        ctx = SkillContext(parameters={"flag": False})
        assert evaluator.evaluate("parameters.flag == false", ctx) is True

    def test_parenthesized_expr(self, evaluator):
        ctx = SkillContext(parameters={"a": 1, "b": 2})
        assert evaluator.evaluate("(parameters.a > 0) and (parameters.b > 0)", ctx) is True
