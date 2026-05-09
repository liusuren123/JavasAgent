"""AutomationEngine 自动化引擎测试。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.automation_engine import AutomationEngine
from src.tools.automation_models import (
    ActionType,
    AutomationRule,
    RuleStats,
    TriggerType,
    compare_values,
    match_cron,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_data_dir(tmp_path):
    """创建临时数据目录。"""
    return tmp_path / "data"


@pytest.fixture
def engine(tmp_data_dir):
    """创建使用临时目录的引擎实例。"""
    return AutomationEngine(config={"data_dir": str(tmp_data_dir)})


@pytest.fixture
def sample_rule_params():
    """标准规则参数。"""
    return {
        "rule_id": "test_rule_1",
        "name": "测试规则",
        "trigger_type": "file_change",
        "trigger_config": {"path": "/tmp/test.log", "check": "modified"},
        "action_type": "log",
        "action_config": {"message": "文件已变化", "level": "info"},
    }


# ---------------------------------------------------------------------------
# 添加规则
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_rule(engine, sample_rule_params):
    """测试添加规则。"""
    result = await engine.execute("add_rule", sample_rule_params)
    assert result["success"] is True
    assert result["data"]["rule_id"] == "test_rule_1"
    assert result["data"]["name"] == "测试规则"
    assert result["data"]["trigger_type"] == "file_change"
    assert result["data"]["action_type"] == "log"
    assert result["data"]["enabled"] is True


@pytest.mark.asyncio
async def test_add_rule_duplicate(engine, sample_rule_params):
    """测试添加重复规则。"""
    await engine.execute("add_rule", sample_rule_params)
    result = await engine.execute("add_rule", sample_rule_params)
    assert result["success"] is False
    assert "已存在" in result["error"]


@pytest.mark.asyncio
async def test_add_rule_missing_params(engine):
    """测试添加规则缺少参数。"""
    assert (await engine.execute("add_rule", {}))["success"] is False
    assert (await engine.execute("add_rule", {"rule_id": "r1"}))["success"] is False
    assert (await engine.execute("add_rule", {"rule_id": "r1", "name": "n"}))["success"] is False


@pytest.mark.asyncio
async def test_add_rule_invalid_trigger_type(engine):
    """测试无效触发器类型。"""
    result = await engine.execute("add_rule", {
        "rule_id": "r1", "name": "n", "trigger_type": "invalid",
    })
    assert result["success"] is False
    assert "trigger_type" in result["error"]


@pytest.mark.asyncio
async def test_add_rule_invalid_action_type(engine):
    """测试无效动作类型。"""
    result = await engine.execute("add_rule", {
        "rule_id": "r1", "name": "n", "trigger_type": "file_change", "action_type": "invalid",
    })
    assert result["success"] is False
    assert "action_type" in result["error"]


# ---------------------------------------------------------------------------
# 删除规则
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_rule(engine, sample_rule_params):
    """测试删除规则。"""
    await engine.execute("add_rule", sample_rule_params)
    result = await engine.execute("remove_rule", {"rule_id": "test_rule_1"})
    assert result["success"] is True
    assert result["data"]["removed_rule_id"] == "test_rule_1"


@pytest.mark.asyncio
async def test_remove_rule_not_found(engine):
    """测试删除不存在的规则。"""
    result = await engine.execute("remove_rule", {"rule_id": "nonexistent"})
    assert result["success"] is False


@pytest.mark.asyncio
async def test_remove_rule_missing_id(engine):
    """测试删除规则缺少 ID。"""
    result = await engine.execute("remove_rule", {})
    assert result["success"] is False


# ---------------------------------------------------------------------------
# 列出规则
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_rules_empty(engine):
    """测试空规则列表。"""
    result = await engine.execute("list_rules", {})
    assert result["success"] is True
    assert result["data"]["count"] == 0
    assert result["data"]["rules"] == []


@pytest.mark.asyncio
async def test_list_rules(engine, sample_rule_params):
    """测试列出规则。"""
    await engine.execute("add_rule", sample_rule_params)
    result = await engine.execute("list_rules", {})
    assert result["success"] is True
    assert result["data"]["count"] == 1


@pytest.mark.asyncio
async def test_list_rules_enabled_only(engine):
    """测试只列出启用规则。"""
    await engine.execute("add_rule", {
        "rule_id": "r1", "name": "启用的", "trigger_type": "file_change", "enabled": True,
    })
    await engine.execute("add_rule", {
        "rule_id": "r2", "name": "禁用的", "trigger_type": "file_change", "enabled": False,
    })
    result = await engine.execute("list_rules", {"enabled_only": True})
    assert result["success"] is True
    assert result["data"]["count"] == 1
    assert result["data"]["rules"][0]["rule_id"] == "r1"


# ---------------------------------------------------------------------------
# 启用/禁用
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enable_disable_rule(engine, sample_rule_params):
    """测试启用和禁用规则。"""
    await engine.execute("add_rule", sample_rule_params)

    result = await engine.execute("disable_rule", {"rule_id": "test_rule_1"})
    assert result["success"] is True
    assert result["data"]["enabled"] is False

    result = await engine.execute("enable_rule", {"rule_id": "test_rule_1"})
    assert result["success"] is True
    assert result["data"]["enabled"] is True


@pytest.mark.asyncio
async def test_enable_rule_not_found(engine):
    """测试启用不存在的规则。"""
    result = await engine.execute("enable_rule", {"rule_id": "nope"})
    assert result["success"] is False


# ---------------------------------------------------------------------------
# 触发器评估
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_file_trigger_no_path(engine):
    """文件触发器无路径不触发。"""
    rule = AutomationRule(rule_id="r1", name="t", trigger_type="file_change", trigger_config={})
    assert await engine._evaluate_file_trigger(rule) is False


@pytest.mark.asyncio
async def test_file_trigger_nonexistent(engine):
    """文件触发器：文件不存在不触发。"""
    rule = AutomationRule(rule_id="r1", name="t", trigger_type="file_change",
                          trigger_config={"path": "/nonexistent/file.txt"})
    assert await engine._evaluate_file_trigger(rule) is False


@pytest.mark.asyncio
async def test_file_trigger_first_check(tmp_path, engine):
    """文件触发器首次检查不触发。"""
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello")
    rule = AutomationRule(rule_id="r1", name="t", trigger_type="file_change",
                          trigger_config={"path": str(test_file)})
    assert await engine._evaluate_file_trigger(rule) is False


@pytest.mark.asyncio
async def test_file_trigger_modified(tmp_path, engine):
    """文件触发器：修改后触发。"""
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello")
    rule = AutomationRule(rule_id="r1", name="t", trigger_type="file_change",
                          trigger_config={"path": str(test_file)})
    # 首次检查
    await engine._evaluate_file_trigger(rule)
    # 修改文件
    import time
    time.sleep(0.05)
    test_file.write_text("world")
    assert await engine._evaluate_file_trigger(rule) is True


@pytest.mark.asyncio
async def test_file_trigger_size_changed(tmp_path, engine):
    """文件触发器：大小变化触发。"""
    test_file = tmp_path / "test.txt"
    test_file.write_text("a")
    rule = AutomationRule(rule_id="r1", name="t", trigger_type="file_change",
                          trigger_config={"path": str(test_file), "check": "size_changed"})
    await engine._evaluate_file_trigger(rule)
    test_file.write_text("aaa")
    assert await engine._evaluate_file_trigger(rule) is True


@pytest.mark.asyncio
async def test_schedule_trigger_interval(engine):
    """定时触发器：interval 模式。"""
    rule = AutomationRule(rule_id="r1", name="t", trigger_type="schedule",
                          trigger_config={"interval_seconds": 60})
    # 无 last_triggered → 触发
    assert await engine._evaluate_schedule_trigger(rule) is True
    # 设置最近触发时间 → 不触发
    rule.last_triggered = datetime.now()
    assert await engine._evaluate_schedule_trigger(rule) is False


@pytest.mark.asyncio
async def test_schedule_trigger_cron(engine):
    """定时触发器：cron 模式。"""
    rule = AutomationRule(rule_id="r1", name="t", trigger_type="schedule",
                          trigger_config={"cron": "* * * * *"})
    assert await engine._evaluate_schedule_trigger(rule) is True


@pytest.mark.asyncio
async def test_system_trigger_cpu(engine):
    """系统触发器：CPU 指标。"""
    rule = AutomationRule(rule_id="r1", name="t", trigger_type="system_event",
                          trigger_config={"metric": "cpu_percent", "threshold": 0, "op": ">"})
    with patch.object(AutomationEngine, "_get_system_metric", return_value=50.0):
        assert await engine._evaluate_system_trigger(rule) is True


@pytest.mark.asyncio
async def test_system_trigger_unknown_metric(engine):
    """系统触发器：未知指标。"""
    rule = AutomationRule(rule_id="r1", name="t", trigger_type="system_event",
                          trigger_config={"metric": "unknown_metric", "threshold": 0, "op": ">"})
    with patch.object(AutomationEngine, "_get_system_metric", return_value=None):
        assert await engine._evaluate_system_trigger(rule) is False


@pytest.mark.asyncio
async def test_process_trigger_running(engine):
    """进程触发器：检查进程运行。"""
    rule = AutomationRule(rule_id="r1", name="t", trigger_type="process_event",
                          trigger_config={"process_name": "python", "event": "running"})
    with patch.object(AutomationEngine, "_is_process_running", return_value=True):
        assert await engine._evaluate_process_trigger(rule) is True


@pytest.mark.asyncio
async def test_process_trigger_stopped(engine):
    """进程触发器：检查进程停止。"""
    rule = AutomationRule(rule_id="r1", name="t", trigger_type="process_event",
                          trigger_config={"process_name": "nonexistent", "event": "stopped"})
    with patch.object(AutomationEngine, "_is_process_running", return_value=False):
        assert await engine._evaluate_process_trigger(rule) is True


# ---------------------------------------------------------------------------
# check_triggers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_triggers_all(engine):
    """测试检查所有触发器。"""
    await engine.execute("add_rule", {
        "rule_id": "r1", "name": "n", "trigger_type": "schedule",
        "trigger_config": {"interval_seconds": 99999},
    })
    result = await engine.execute("check_triggers", {})
    assert result["success"] is True
    assert result["data"]["checked_count"] == 1


@pytest.mark.asyncio
async def test_check_triggers_specific(engine):
    """测试检查指定规则触发器。"""
    await engine.execute("add_rule", {
        "rule_id": "r1", "name": "n", "trigger_type": "schedule",
        "trigger_config": {"interval_seconds": 1},
    })
    result = await engine.execute("check_triggers", {"rule_id": "r1"})
    assert result["success"] is True
    assert result["data"]["checked_count"] == 1


@pytest.mark.asyncio
async def test_check_triggers_not_found(engine):
    """测试检查不存在的规则。"""
    result = await engine.execute("check_triggers", {"rule_id": "nope"})
    assert result["success"] is False


# ---------------------------------------------------------------------------
# fire_rule
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fire_rule_log(engine):
    """测试触发 log 规则。"""
    await engine.execute("add_rule", {
        "rule_id": "r1", "name": "n", "trigger_type": "schedule",
        "trigger_config": {"cron": "* * * * *"},
        "action_type": "log",
        "action_config": {"message": "测试日志"},
    })
    result = await engine.execute("fire_rule", {"rule_id": "r1"})
    assert result["success"] is True
    assert result["data"]["action_result"]["action"] == "log"


@pytest.mark.asyncio
async def test_fire_rule_notify(engine):
    """测试触发 notify 规则。"""
    await engine.execute("add_rule", {
        "rule_id": "r1", "name": "n", "trigger_type": "schedule",
        "action_type": "notify",
        "action_config": {"message": "通知消息", "title": "标题"},
    })
    result = await engine.execute("fire_rule", {"rule_id": "r1"})
    assert result["success"] is True
    assert result["data"]["action_result"]["action"] == "notify"


@pytest.mark.asyncio
async def test_fire_rule_run_tool(engine):
    """测试触发 run_tool 规则（echo 命令）。"""
    await engine.execute("add_rule", {
        "rule_id": "r1", "name": "n", "trigger_type": "schedule",
        "action_type": "run_tool",
        "action_config": {"command": "echo hello"},
    })
    result = await engine.execute("fire_rule", {"rule_id": "r1"})
    assert result["success"] is True
    assert "hello" in result["data"]["action_result"]["stdout"]


@pytest.mark.asyncio
async def test_fire_rule_missing_id(engine):
    """测试触发规则缺少 ID。"""
    result = await engine.execute("fire_rule", {})
    assert result["success"] is False


@pytest.mark.asyncio
async def test_fire_rule_not_found(engine):
    """测试触发不存在的规则。"""
    result = await engine.execute("fire_rule", {"rule_id": "nope"})
    assert result["success"] is False


# ---------------------------------------------------------------------------
# get_rule_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_rule_status(engine):
    """测试获取规则状态。"""
    await engine.execute("add_rule", {
        "rule_id": "r1", "name": "n", "trigger_type": "schedule",
        "action_type": "log", "action_config": {"message": "m"},
    })
    await engine.execute("fire_rule", {"rule_id": "r1"})

    result = await engine.execute("get_rule_status", {"rule_id": "r1"})
    assert result["success"] is True
    assert result["data"]["stats"]["trigger_count"] == 1
    assert result["data"]["stats"]["success_count"] == 1
    assert result["data"]["stats"]["failure_count"] == 0


@pytest.mark.asyncio
async def test_get_rule_status_not_found(engine):
    """测试获取不存在规则的状态。"""
    result = await engine.execute("get_rule_status", {"rule_id": "nope"})
    assert result["success"] is False


# ---------------------------------------------------------------------------
# 统计信息
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stats_increment_on_fire(engine):
    """测试触发规则后统计递增。"""
    await engine.execute("add_rule", {
        "rule_id": "r1", "name": "n", "trigger_type": "schedule",
        "action_type": "log", "action_config": {"message": "m"},
    })
    await engine.execute("fire_rule", {"rule_id": "r1"})
    await engine.execute("fire_rule", {"rule_id": "r1"})

    result = await engine.execute("get_rule_status", {"rule_id": "r1"})
    assert result["data"]["stats"]["trigger_count"] == 2
    assert result["data"]["stats"]["success_count"] == 2


@pytest.mark.asyncio
async def test_stats_failure_count(engine):
    """测试执行失败时统计。"""
    await engine.execute("add_rule", {
        "rule_id": "r1", "name": "n", "trigger_type": "schedule",
        "action_type": "run_tool",
        "action_config": {"command": ""},  # 空命令会失败
    })
    result = await engine.execute("fire_rule", {"rule_id": "r1"})
    assert result["success"] is False

    status = await engine.execute("get_rule_status", {"rule_id": "r1"})
    assert status["data"]["stats"]["failure_count"] == 1


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_and_load(tmp_data_dir):
    """测试规则保存和重新加载。"""
    engine1 = AutomationEngine(config={"data_dir": str(tmp_data_dir)})
    await engine1.execute("add_rule", {
        "rule_id": "r1", "name": "持久化规则", "trigger_type": "file_change",
        "trigger_config": {"path": "/tmp/test"}, "action_type": "log",
    })
    await engine1.execute("fire_rule", {"rule_id": "r1"})

    # 重新创建引擎，应自动加载
    engine2 = AutomationEngine(config={"data_dir": str(tmp_data_dir)})
    result = await engine2.execute("list_rules", {})
    assert result["data"]["count"] == 1
    assert result["data"]["rules"][0]["name"] == "持久化规则"

    # 统计也应保留
    status = await engine2.execute("get_rule_status", {"rule_id": "r1"})
    assert status["data"]["stats"]["trigger_count"] == 1


@pytest.mark.asyncio
async def test_load_corrupted_file(tmp_data_dir):
    """测试加载损坏的规则文件。"""
    rules_file = Path(tmp_data_dir) / "automation_rules.json"
    rules_file.parent.mkdir(parents=True, exist_ok=True)
    rules_file.write_text("not valid json{{{", encoding="utf-8")

    engine = AutomationEngine(config={"data_dir": str(tmp_data_dir)})
    result = await engine.execute("list_rules", {})
    assert result["data"]["count"] == 0


# ---------------------------------------------------------------------------
# RuleStats 数据类
# ---------------------------------------------------------------------------

def test_rule_stats_record():
    """测试 RuleStats 记录方法。"""
    stats = RuleStats(rule_id="r1")
    stats.record_trigger()
    assert stats.trigger_count == 1
    assert stats.last_trigger_time is not None

    stats.record_success()
    assert stats.success_count == 1

    stats.record_failure("test error")
    assert stats.failure_count == 1
    assert stats.last_error == "test error"


def test_rule_stats_to_dict():
    """测试 RuleStats 序列化。"""
    stats = RuleStats(rule_id="r1", trigger_count=5, success_count=3, failure_count=2)
    d = stats.to_dict()
    assert d["rule_id"] == "r1"
    assert d["trigger_count"] == 5
    assert d["success_count"] == 3
    assert d["failure_count"] == 2


# ---------------------------------------------------------------------------
# AutomationRule 数据类
# ---------------------------------------------------------------------------

def test_rule_to_dict_roundtrip():
    """测试 AutomationRule 序列化/反序列化。"""
    rule = AutomationRule(
        rule_id="r1", name="test", trigger_type="file_change",
        trigger_config={"path": "/tmp"}, action_type="log",
        action_config={"message": "hi"}, enabled=True,
    )
    d = rule.to_dict()
    restored = AutomationRule.from_dict(d)
    assert restored.rule_id == rule.rule_id
    assert restored.name == rule.name
    assert restored.trigger_type == rule.trigger_type
    assert restored.trigger_config == rule.trigger_config


def test_rule_from_dict_with_last_triggered():
    """测试带 last_triggered 的反序列化。"""
    now = datetime.now().isoformat()
    rule = AutomationRule.from_dict({
        "rule_id": "r1", "name": "t", "trigger_type": "schedule",
        "last_triggered": now,
    })
    assert rule.last_triggered is not None


# ---------------------------------------------------------------------------
# Cron 匹配
# ---------------------------------------------------------------------------

def test_cron_match_wildcard():
    """测试 cron 通配符匹配。"""
    assert match_cron("* * * * *") is True


def test_cron_invalid():
    """测试无效 cron 表达式。"""
    assert match_cron("* * *") is False
    assert match_cron("") is False


def test_cron_specific_values():
    """测试 cron 具体值匹配。"""
    now = datetime.now()
    expr = f"{now.minute} {now.hour} {now.day} {now.month} {now.weekday()}"
    assert match_cron(expr) is True


def test_cron_range():
    """测试 cron 范围匹配。"""
    # 当前分钟一定在 0-59 范围内
    assert match_cron("0-59 * * * *") is True


def test_cron_step():
    """测试 cron 步进匹配。"""
    assert match_cron("*/1 * * * *") is True


# ---------------------------------------------------------------------------
# compare_values
# ---------------------------------------------------------------------------

def test_compare_values():
    """测试值比较函数。"""
    assert compare_values(10, 5, ">") is True
    assert compare_values(5, 10, ">") is False
    assert compare_values(10, 10, ">=") is True
    assert compare_values(5, 10, "<") is True
    assert compare_values(10, 10, "<=") is True
    assert compare_values(10, 10, "==") is True
    assert compare_values(10, 5, "unknown") is False


# ---------------------------------------------------------------------------
# 未知操作
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_action(engine):
    """测试未知操作。"""
    result = await engine.execute("unknown_action", {})
    assert result["success"] is False
    assert "未知操作" in result["error"]


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------

def test_trigger_type_enum():
    """测试 TriggerType 枚举。"""
    assert TriggerType.FILE_CHANGE.value == "file_change"
    assert TriggerType.SCHEDULE.value == "schedule"
    assert TriggerType.SYSTEM_EVENT.value == "system_event"
    assert TriggerType.PROCESS_EVENT.value == "process_event"


def test_action_type_enum():
    """测试 ActionType 枚举。"""
    assert ActionType.RUN_TOOL.value == "run_tool"
    assert ActionType.NOTIFY.value == "notify"
    assert ActionType.LOG.value == "log"
