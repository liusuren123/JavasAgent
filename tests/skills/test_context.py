# -*- coding: utf-8 -*-
"""SkillContext 测试。"""

import pytest

from src.skills.context import SkillContext


class TestSkillContextGet:
    """测试 get() 点号路径解析。"""

    def test_get_parameter_direct(self):
        ctx = SkillContext(parameters={"filename": "test.txt"})
        assert ctx.get("parameters.filename") == "test.txt"

    def test_get_variable_direct(self):
        ctx = SkillContext(variables={"count": 42})
        assert ctx.get("variables.count") == 42

    def test_get_result_direct(self):
        ctx = SkillContext(result={"status": "ok"})
        assert ctx.get("result.status") == "ok"

    def test_get_nested_path(self):
        ctx = SkillContext(parameters={"file": {"name": "report.pdf", "size": 1024}})
        assert ctx.get("parameters.file.name") == "report.pdf"
        assert ctx.get("parameters.file.size") == 1024

    def test_get_without_namespace_prefers_variables(self):
        ctx = SkillContext(parameters={"x": 1}, variables={"x": 2})
        assert ctx.get("x") == 2  # variables 优先

    def test_get_without_namespace_fallback_parameters(self):
        ctx = SkillContext(parameters={"x": 1})
        assert ctx.get("x") == 1

    def test_get_missing_returns_default(self):
        ctx = SkillContext()
        assert ctx.get("nonexistent") is None
        assert ctx.get("nonexistent", 0) == 0

    def test_get_deep_missing_path(self):
        ctx = SkillContext(parameters={"a": {"b": 1}})
        assert ctx.get("parameters.a.c") is None


class TestSkillContextSet:
    """测试 set() 变量存储。"""

    def test_set_simple(self):
        ctx = SkillContext()
        ctx.set("count", 10)
        assert ctx.variables["count"] == 10

    def test_set_with_variables_prefix(self):
        ctx = SkillContext()
        ctx.set("variables.count", 5)
        assert ctx.variables["count"] == 5

    def test_set_nested(self):
        ctx = SkillContext()
        ctx.set("variables.stats.count", 99)
        assert ctx.variables["stats"]["count"] == 99


class TestSkillContextResolve:
    """测试 resolve() 模板变量替换。"""

    def test_resolve_simple(self):
        ctx = SkillContext(parameters={"filename": "test.txt"})
        assert ctx.resolve("{{filename}}") == "test.txt"

    def test_resolve_with_prefix(self):
        ctx = SkillContext(parameters={"filename": "report.pdf"})
        assert ctx.resolve("{{parameters.filename}}") == "report.pdf"

    def test_resolve_multiple_vars(self):
        ctx = SkillContext(parameters={"name": "foo", "ext": "txt"})
        assert ctx.resolve("{{name}}.{{ext}}") == "foo.txt"

    def test_resolve_missing_keeps_template(self):
        ctx = SkillContext()
        assert ctx.resolve("{{nonexistent}}") == "{{nonexistent}}"

    def test_resolve_non_string_passthrough(self):
        ctx = SkillContext()
        assert ctx.resolve(42) == 42
        assert ctx.resolve(None) is None

    def test_resolve_no_template(self):
        ctx = SkillContext(parameters={"x": "y"})
        assert ctx.resolve("plain text") == "plain text"

    def test_resolve_variable(self):
        ctx = SkillContext(variables={"greeting": "hello"})
        assert ctx.resolve("{{variables.greeting}}") == "hello"


class TestSkillContextToDict:
    """测试 to_dict() 序列化。"""

    def test_to_dict(self):
        ctx = SkillContext(
            parameters={"a": 1},
            variables={"b": 2},
            result={"c": 3},
            current_step=1,
            total_steps=5,
        )
        d = ctx.to_dict()
        assert d["parameters"] == {"a": 1}
        assert d["variables"] == {"b": 2}
        assert d["result"] == {"c": 3}
        assert d["current_step"] == 1
        assert d["total_steps"] == 5
        assert d["screenshots_count"] == 0
