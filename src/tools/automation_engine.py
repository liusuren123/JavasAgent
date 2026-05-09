"""自动化引擎 — 事件驱动规则系统。

支持文件变化、定时调度、系统事件和进程事件四种触发器类型，
以及 run_tool、notify、log 三种动作类型。
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil
from loguru import logger

from src.tools.automation_models import (
    ActionType,
    AutomationRule,
    RuleStats,
    TriggerType,
    compare_values,
    match_cron,
)


class AutomationEngine:
    """自动化引擎。

    操作入口:
    - add_rule / remove_rule / list_rules — 规则增删查
    - enable_rule / disable_rule — 启用/禁用
    - check_triggers — 检查触发条件
    - fire_rule — 手动触发规则
    - get_rule_status — 获取运行统计

    Usage::

        engine = AutomationEngine()
        await engine.execute("add_rule", {
            "rule_id": "r1", "name": "监控日志",
            "trigger_type": "file_change",
            "trigger_config": {"path": "/var/log/app.log"},
            "action_type": "log",
            "action_config": {"message": "文件变化"},
        })
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._rules: dict[str, AutomationRule] = {}
        self._stats: dict[str, RuleStats] = {}
        self._file_state_cache: dict[str, dict[str, Any]] = {}

        data_dir = self._config.get("data_dir", "data")
        self._rules_file = Path(data_dir) / "automation_rules.json"

        self._actions: dict[str, Any] = {
            "add_rule": self._add_rule,
            "remove_rule": self._remove_rule,
            "list_rules": self._list_rules,
            "enable_rule": self._enable_rule,
            "disable_rule": self._disable_rule,
            "check_triggers": self._check_triggers,
            "fire_rule": self._fire_rule,
            "get_rule_status": self._get_rule_status,
        }
        self._load_rules()

    # ------------------------------------------------------------------
    # 统一入口
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行自动化引擎操作。

        Args:
            action: 操作类型
            params: 操作参数

        Returns:
            包含 success 和 data/error 的结果字典
        """
        handler = self._actions.get(action)
        if handler is None:
            logger.error(f"未知操作: {action}")
            return {
                "success": False,
                "error": f"未知操作: {action}，支持: {', '.join(sorted(self._actions.keys()))}",
            }
        try:
            return await handler(params)
        except Exception as e:
            logger.error(f"自动化引擎操作失败 [{action}]: {e}")
            return {"success": False, "error": f"操作失败: {e}"}

    # ------------------------------------------------------------------
    # 规则 CRUD
    # ------------------------------------------------------------------

    async def _add_rule(self, params: dict[str, Any]) -> dict[str, Any]:
        """添加规则。需要 rule_id, name, trigger_type。"""
        rule_id = params.get("rule_id")
        name = params.get("name")
        trigger_type = params.get("trigger_type")
        if not rule_id:
            return {"success": False, "error": "缺少参数: rule_id"}
        if not name:
            return {"success": False, "error": "缺少参数: name"}
        if not trigger_type:
            return {"success": False, "error": "缺少参数: trigger_type"}

        valid_triggers = [t.value for t in TriggerType]
        if trigger_type not in valid_triggers:
            return {"success": False, "error": f"无效 trigger_type，支持: {', '.join(valid_triggers)}"}

        action_type = params.get("action_type", "log")
        valid_actions = [a.value for a in ActionType]
        if action_type not in valid_actions:
            return {"success": False, "error": f"无效 action_type，支持: {', '.join(valid_actions)}"}

        if rule_id in self._rules:
            return {"success": False, "error": f"规则已存在: {rule_id}"}

        rule = AutomationRule(
            rule_id=rule_id, name=name, trigger_type=trigger_type,
            trigger_config=params.get("trigger_config", {}),
            action_type=action_type,
            action_config=params.get("action_config", {}),
            enabled=params.get("enabled", True),
        )
        self._rules[rule_id] = rule
        self._stats[rule_id] = RuleStats(rule_id=rule_id)
        self._save_rules()
        logger.info(f"添加自动化规则: {rule_id} ({name})")
        return {"success": True, "data": rule.to_dict()}

    async def _remove_rule(self, params: dict[str, Any]) -> dict[str, Any]:
        """删除规则。需要 rule_id。"""
        rule_id = params.get("rule_id")
        if not rule_id:
            return {"success": False, "error": "缺少参数: rule_id"}
        if rule_id not in self._rules:
            return {"success": False, "error": f"规则不存在: {rule_id}"}

        removed = self._rules.pop(rule_id)
        self._stats.pop(rule_id, None)
        self._file_state_cache.pop(rule_id, None)
        self._save_rules()
        logger.info(f"删除自动化规则: {rule_id}")
        return {"success": True, "data": {"removed_rule_id": rule_id, "name": removed.name}}

    async def _list_rules(self, params: dict[str, Any]) -> dict[str, Any]:
        """列出所有规则。支持 enabled_only 过滤。"""
        enabled_only = params.get("enabled_only", False)
        rules = list(self._rules.values())
        if enabled_only:
            rules = [r for r in rules if r.enabled]
        return {"success": True, "data": {"rules": [r.to_dict() for r in rules], "count": len(rules)}}

    async def _enable_rule(self, params: dict[str, Any]) -> dict[str, Any]:
        """启用规则。需要 rule_id。"""
        return await self._set_rule_enabled(params, True)

    async def _disable_rule(self, params: dict[str, Any]) -> dict[str, Any]:
        """禁用规则。需要 rule_id。"""
        return await self._set_rule_enabled(params, False)

    # ------------------------------------------------------------------
    # 触发器检查与执行
    # ------------------------------------------------------------------

    async def _check_triggers(self, params: dict[str, Any]) -> dict[str, Any]:
        """检查触发条件。可选 rule_id 指定单条规则。"""
        rule_id = params.get("rule_id")
        if rule_id:
            if rule_id not in self._rules:
                return {"success": False, "error": f"规则不存在: {rule_id}"}
            rules_to_check = [self._rules[rule_id]]
        else:
            rules_to_check = [r for r in self._rules.values() if r.enabled]

        results: list[dict[str, Any]] = []
        for rule in rules_to_check:
            try:
                triggered = await self._evaluate_trigger(rule)
                results.append({"rule_id": rule.rule_id, "name": rule.name, "triggered": triggered})
            except Exception as e:
                results.append({"rule_id": rule.rule_id, "name": rule.name, "triggered": False, "error": str(e)})

        triggered_count = sum(1 for r in results if r["triggered"])
        return {"success": True, "data": {"results": results, "checked_count": len(results), "triggered_count": triggered_count}}

    async def _fire_rule(self, params: dict[str, Any]) -> dict[str, Any]:
        """手动触发规则。需要 rule_id。"""
        rule_id = params.get("rule_id")
        if not rule_id:
            return {"success": False, "error": "缺少参数: rule_id"}
        if rule_id not in self._rules:
            return {"success": False, "error": f"规则不存在: {rule_id}"}

        rule = self._rules[rule_id]
        stats = self._stats.get(rule_id)
        try:
            action_result = await self._execute_action(rule)
            rule.last_triggered = datetime.now()
            if stats:
                stats.record_trigger()
                stats.record_success()
            self._save_rules()
            logger.info(f"手动触发规则: {rule_id} ({rule.name})")
            return {"success": True, "data": {"rule_id": rule_id, "action_result": action_result}}
        except Exception as e:
            if stats:
                stats.record_trigger()
                stats.record_failure(str(e))
            logger.error(f"触发规则失败 [{rule_id}]: {e}")
            return {"success": False, "error": f"触发规则失败: {e}"}

    async def _get_rule_status(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取规则状态和统计。需要 rule_id。"""
        rule_id = params.get("rule_id")
        if not rule_id:
            return {"success": False, "error": "缺少参数: rule_id"}
        if rule_id not in self._rules:
            return {"success": False, "error": f"规则不存在: {rule_id}"}

        rule = self._rules[rule_id]
        stats = self._stats.get(rule_id, RuleStats(rule_id=rule_id))
        return {"success": True, "data": {"rule": rule.to_dict(), "stats": stats.to_dict()}}

    # ------------------------------------------------------------------
    # 触发器评估
    # ------------------------------------------------------------------

    async def _evaluate_trigger(self, rule: AutomationRule) -> bool:
        """评估触发条件。"""
        evaluator = {
            TriggerType.FILE_CHANGE.value: self._evaluate_file_trigger,
            TriggerType.SCHEDULE.value: self._evaluate_schedule_trigger,
            TriggerType.SYSTEM_EVENT.value: self._evaluate_system_trigger,
            TriggerType.PROCESS_EVENT.value: self._evaluate_process_trigger,
        }.get(rule.trigger_type)
        if evaluator is None:
            return False
        return await evaluator(rule)

    async def _evaluate_file_trigger(self, rule: AutomationRule) -> bool:
        """检查文件变化。配置: path, check(exists/size_changed/modified)。"""
        path = rule.trigger_config.get("path", "")
        if not path:
            return False
        check_type = rule.trigger_config.get("check", "modified")
        try:
            p = Path(path)
            if not p.exists():
                self._file_state_cache[rule.rule_id] = {"exists": False}
                return False

            stat = p.stat()
            current = {"exists": True, "size": stat.st_size, "mtime": stat.st_mtime}
            previous = self._file_state_cache.get(rule.rule_id)
            self._file_state_cache[rule.rule_id] = current

            if previous is None:
                return False
            if check_type == "exists":
                return not previous.get("exists", False) and current["exists"]
            if check_type == "size_changed":
                return previous.get("size") != current["size"]
            return previous.get("mtime") != current["mtime"]
        except OSError as e:
            logger.warning(f"文件触发器检查失败: {e}")
            return False

    async def _evaluate_schedule_trigger(self, rule: AutomationRule) -> bool:
        """检查定时触发。配置: cron 或 interval_seconds。"""
        interval = rule.trigger_config.get("interval_seconds")
        if interval is not None:
            if rule.last_triggered is None:
                return True
            return (datetime.now() - rule.last_triggered).total_seconds() >= interval

        cron = rule.trigger_config.get("cron")
        if cron:
            return match_cron(cron)
        return False

    async def _evaluate_system_trigger(self, rule: AutomationRule) -> bool:
        """检查系统指标。配置: metric, threshold, op。"""
        metric = rule.trigger_config.get("metric", "")
        threshold = rule.trigger_config.get("threshold", 100.0)
        op = rule.trigger_config.get("op", ">")
        try:
            current = self._get_system_metric(metric)
            if current is None:
                return False
            return compare_values(current, threshold, op)
        except Exception as e:
            logger.warning(f"系统触发器检查失败: {e}")
            return False

    async def _evaluate_process_trigger(self, rule: AutomationRule) -> bool:
        """检查进程事件。配置: process_name, event(running/stopped)。"""
        proc_name = rule.trigger_config.get("process_name", "")
        if not proc_name:
            return False
        event = rule.trigger_config.get("event", "running")
        running = self._is_process_running(proc_name)
        if event == "running":
            return running
        return not running

    # ------------------------------------------------------------------
    # 动作执行
    # ------------------------------------------------------------------

    async def _execute_action(self, rule: AutomationRule) -> dict[str, Any]:
        """执行动作。"""
        executor = {
            ActionType.RUN_TOOL.value: self._action_run_tool,
            ActionType.NOTIFY.value: self._action_notify,
            ActionType.LOG.value: self._action_log,
        }.get(rule.action_type)
        if executor is None:
            raise ValueError(f"未知动作类型: {rule.action_type}")
        return await executor(rule)

    async def _action_run_tool(self, rule: AutomationRule) -> dict[str, Any]:
        """run_tool 动作：执行 shell 命令。配置: command, timeout。"""
        command = rule.action_config.get("command", "")
        if not command:
            raise ValueError("run_tool 缺少 command")
        timeout = rule.action_config.get("timeout", 60)
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
            return {"action": "run_tool", "returncode": result.returncode,
                    "stdout": result.stdout[:2000], "stderr": (result.stderr or "")[:1000]}
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"命令超时 ({timeout}s): {command}")

    async def _action_notify(self, rule: AutomationRule) -> dict[str, Any]:
        """notify 动作。配置: message, title。"""
        msg = rule.action_config.get("message", "")
        title = rule.action_config.get("title", rule.name)
        logger.info(f"[通知] {title}: {msg}")
        return {"action": "notify", "title": title, "message": msg}

    async def _action_log(self, rule: AutomationRule) -> dict[str, Any]:
        """log 动作。配置: message, level。"""
        msg = rule.action_config.get("message", f"规则 {rule.name} 被触发")
        level = rule.action_config.get("level", "info")
        {"info": logger.info, "warning": logger.warning, "error": logger.error}.get(level, logger.info)(
            f"[AutomationEngine] {msg}"
        )
        return {"action": "log", "level": level, "message": msg}

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _save_rules(self) -> None:
        """保存规则和统计到 JSON 文件。"""
        try:
            self._rules_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "rules": [r.to_dict() for r in self._rules.values()],
                "stats": {rid: s.to_dict() for rid, s in self._stats.items()},
            }
            tmp = self._rules_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._rules_file)
        except Exception as e:
            logger.error(f"保存规则失败: {e}")

    def _load_rules(self) -> None:
        """从 JSON 文件加载规则和统计。"""
        if not self._rules_file.exists():
            return
        try:
            raw = self._rules_file.read_text(encoding="utf-8")
            data = json.loads(raw)

            for r in data.get("rules", []):
                rule = AutomationRule.from_dict(r)
                self._rules[rule.rule_id] = rule

            for s in data.get("stats", {}).values():
                stats = RuleStats(
                    rule_id=s["rule_id"],
                    trigger_count=s.get("trigger_count", 0),
                    success_count=s.get("success_count", 0),
                    failure_count=s.get("failure_count", 0),
                    last_error=s.get("last_error", ""),
                )
                for fn in ("last_trigger_time", "last_success_time", "last_failure_time"):
                    val = s.get(fn)
                    if isinstance(val, str):
                        setattr(stats, fn, datetime.fromisoformat(val))
                self._stats[stats.rule_id] = stats

            logger.info(f"已加载 {len(self._rules)} 条自动化规则")
        except Exception as e:
            logger.error(f"加载规则失败: {e}")

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _set_rule_enabled(self, params: dict[str, Any], enabled: bool) -> dict[str, Any]:
        """设置规则启用/禁用。"""
        rule_id = params.get("rule_id")
        if not rule_id:
            return {"success": False, "error": "缺少参数: rule_id"}
        if rule_id not in self._rules:
            return {"success": False, "error": f"规则不存在: {rule_id}"}

        self._rules[rule_id].enabled = enabled
        self._save_rules()
        logger.info(f"{'启用' if enabled else '禁用'}规则: {rule_id}")
        return {"success": True, "data": {"rule_id": rule_id, "enabled": enabled}}

    @staticmethod
    def _get_system_metric(metric: str) -> float | None:
        """获取系统指标值。"""
        if metric == "cpu_percent":
            return psutil.cpu_percent(interval=0.1)
        if metric == "memory_percent":
            return psutil.virtual_memory().percent
        if metric == "disk_percent":
            vals = []
            for part in psutil.disk_partitions():
                try:
                    vals.append(psutil.disk_usage(part.mountpoint).percent)
                except (PermissionError, OSError):
                    continue
            return max(vals) if vals else None
        return None

    @staticmethod
    def _is_process_running(name: str) -> bool:
        """检查进程是否在运行。"""
        name_lower = name.lower()
        for proc in psutil.process_iter():
            try:
                if name_lower in proc.name().lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False
