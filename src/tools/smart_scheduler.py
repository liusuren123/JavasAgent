"""SmartScheduler 智能日程调度工具。

根据用户偏好、日历空闲时间和任务优先级，自动安排工作计划。
提供单任务安排、批量优化、冲突检测和每日计划生成能力。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from loguru import logger

from src.tools.schedule_models import (
    CalendarEvent,
    ConflictInfo,
    DailyPlan,
    Priority,
    SchedulerConfig,
    ScheduleTask,
    ScheduledItem,
    TimeSlot,
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _parse_dt(value: str) -> datetime:
    """解析日期时间字符串。"""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析日期时间: '{value}'")


def _fmt_dt(dt: datetime) -> str:
    """格式化 datetime 为标准字符串。"""
    return dt.strftime("%Y-%m-%d %H:%M")


def _next_work_time(dt: datetime, config: SchedulerConfig) -> datetime:
    """获取下一个工作时间。"""
    candidate = dt
    if candidate.hour < config.work_start_hour:
        candidate = candidate.replace(hour=config.work_start_hour, minute=0, second=0, microsecond=0)
    while candidate.weekday() not in config.work_days or candidate.hour >= config.work_end_hour:
        candidate = (candidate + timedelta(days=1)).replace(
            hour=config.work_start_hour, minute=0, second=0, microsecond=0)
    return candidate


def _compute_free_slots(
    day_start: datetime, day_end: datetime,
    events: list[CalendarEvent], config: SchedulerConfig,
) -> list[TimeSlot]:
    """在一天内扣除已有事件，计算空闲时段。"""
    slots: list[TimeSlot] = []
    busy = sorted(
        ((_parse_dt(e.start), _parse_dt(e.end))
         for e in events if e.is_blocking and e.start and e.end),
        key=lambda x: x[0],
    )
    cursor = day_start
    for bs, be in busy:
        if be <= cursor:
            continue
        if bs >= day_end:
            break
        actual = max(cursor, bs)
        gap = int((actual - cursor).total_seconds() / 60)
        if gap >= config.min_task_duration:
            slots.append(TimeSlot(start=_fmt_dt(cursor), end=_fmt_dt(actual), duration_minutes=gap))
        cursor = max(cursor, be)
    if cursor < day_end:
        gap = int((day_end - cursor).total_seconds() / 60)
        if gap >= config.min_task_duration:
            slots.append(TimeSlot(start=_fmt_dt(cursor), end=_fmt_dt(day_end), duration_minutes=gap))
    return slots


def _sort_tasks(tasks: list[ScheduleTask]) -> list[ScheduleTask]:
    """按优先级降序 + 截止时间升序排列。"""
    return sorted(tasks, key=lambda t: (-t.priority, t.deadline or "9999-12-31"))


def _parse_task(raw: dict[str, Any]) -> ScheduleTask | None:
    """从字典解析任务，失败返回 None。"""
    name = raw.get("task_name") or raw.get("name", "")
    if not name:
        return None
    return ScheduleTask(
        name=name,
        duration_minutes=int(raw.get("duration_minutes", 60)),
        priority=Priority.from_str(raw.get("priority", "normal")),
        deadline=raw.get("deadline"),
        description=raw.get("description", ""),
    )


# ---------------------------------------------------------------------------
# SmartScheduler 主类
# ---------------------------------------------------------------------------

class SmartScheduler:
    """智能日程调度工具。

    Usage::

        scheduler = SmartScheduler(calendar_ops=my_calendar_ops)
        result = await scheduler.execute("schedule_task", {
            "task_name": "写周报", "duration_minutes": 60, "priority": "high",
        })
    """

    def __init__(self, calendar_ops: Any | None = None, config: dict[str, Any] | None = None) -> None:
        self._calendar_ops = calendar_ops
        self._config = SchedulerConfig(**(config or {}))

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """统一执行入口。"""
        handlers = {
            "schedule_task": self._handle_schedule_task,
            "optimize_schedule": self._handle_optimize_schedule,
            "detect_conflicts": self._handle_detect_conflicts,
            "generate_daily_plan": self._handle_generate_daily_plan,
        }
        handler = handlers.get(action)
        if handler is None:
            return {"error": f"未知操作: {action}", "available_actions": sorted(handlers.keys())}
        return await handler(params)

    # ------------------------------------------------------------------
    # 调度单任务
    # ------------------------------------------------------------------

    async def schedule_task(
        self, task_name: str, duration_minutes: int,
        deadline: str | None = None, priority: str = "normal",
        preferred_start: str | None = None,
    ) -> dict[str, Any]:
        """安排单个任务到最佳时间槽。"""
        try:
            task = ScheduleTask(
                name=task_name, duration_minutes=duration_minutes,
                priority=Priority.from_str(priority),
                deadline=deadline, preferred_start=preferred_start,
            )
        except ValueError as e:
            return {"error": str(e)}

        now = datetime.now()
        try:
            search_start = _parse_dt(preferred_start) if preferred_start else _next_work_time(now, self._config)
            search_end = _parse_dt(deadline) if deadline else search_start + timedelta(days=self._config.default_lookahead_days)
        except ValueError as e:
            return {"error": str(e)}

        events = await self._fetch_events(search_start, search_end)

        current_day = search_start.replace(hour=0, minute=0, second=0, microsecond=0)
        while current_day <= search_end:
            day_ws = max(current_day.replace(hour=self._config.work_start_hour, minute=0, second=0, microsecond=0), search_start)
            day_we = min(current_day.replace(hour=self._config.work_end_hour, minute=0, second=0, microsecond=0), search_end)
            if day_ws < day_we:
                day_events = self._filter_events_for_day(events, current_day)
                for slot in _compute_free_slots(day_ws, day_we, day_events, self._config):
                    if slot.duration_minutes >= task.duration_minutes:
                        s = _parse_dt(slot.start)
                        e = s + timedelta(minutes=task.duration_minutes)
                        logger.info(f"任务 '{task.name}' 安排到 {_fmt_dt(s)}")
                        return {
                            "status": "success", "task_name": task.name,
                            "scheduled_start": _fmt_dt(s), "scheduled_end": _fmt_dt(e),
                            "duration_minutes": task.duration_minutes,
                            "priority": task.priority.name.lower(),
                        }
            current_day += timedelta(days=1)

        return {
            "status": "no_slot_found", "task_name": task.name,
            "message": f"在 {_fmt_dt(search_start)} 至 {_fmt_dt(search_end)} 范围内未找到足够空闲时段",
            "suggestion": "可以尝试延长截止时间或缩短任务时长",
        }

    async def _handle_schedule_task(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("task_name", "")
        if not name:
            return {"error": "缺少必要参数: task_name"}
        dur = params.get("duration_minutes")
        if dur is None:
            return {"error": "缺少必要参数: duration_minutes"}
        try:
            dur = int(dur)
        except (ValueError, TypeError):
            return {"error": "duration_minutes 必须为正整数"}
        return await self.schedule_task(name, dur, params.get("deadline"), params.get("priority", "normal"), params.get("preferred_start"))

    # ------------------------------------------------------------------
    # 批量优化日程
    # ------------------------------------------------------------------

    async def optimize_schedule(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        """按优先级和截止时间排序后，逐一安排到空闲时段。"""
        if not tasks:
            return {"error": "任务列表为空"}
        parsed = [t for raw in tasks if (t := _parse_task(raw)) is not None]
        if not parsed:
            return {"error": "没有可安排的有效任务"}
        sorted_tasks = _sort_tasks(parsed)

        now = datetime.now()
        max_dl = now + timedelta(days=self._config.default_lookahead_days)
        for t in sorted_tasks:
            if t.deadline:
                try:
                    dl = _parse_dt(t.deadline)
                    if dl > max_dl:
                        max_dl = dl
                except ValueError:
                    pass

        events = await self._fetch_events(_next_work_time(now, self._config), max_dl)
        scheduled: list[ScheduledItem] = []
        unscheduled: list[str] = []
        booked: list[tuple[datetime, datetime]] = []

        for task in sorted_tasks:
            placed = False
            search_start = _next_work_time(now, self._config)
            search_end = max_dl
            if task.deadline:
                try:
                    search_end = _parse_dt(task.deadline)
                except ValueError:
                    pass
            current_day = search_start.replace(hour=0, minute=0, second=0, microsecond=0)
            while current_day <= search_end and not placed:
                day_ws = max(current_day.replace(hour=self._config.work_start_hour, minute=0, second=0, microsecond=0), search_start)
                day_we = min(current_day.replace(hour=self._config.work_end_hour, minute=0, second=0, microsecond=0), search_end)
                if day_ws < day_we:
                    day_events = self._filter_events_for_day(events, current_day)
                    for bs, be in booked:
                        day_events.append(CalendarEvent(subject="(已安排)", start=_fmt_dt(bs), end=_fmt_dt(be), busy_status="busy"))
                    for slot in _compute_free_slots(day_ws, day_we, day_events, self._config):
                        if slot.duration_minutes >= task.duration_minutes:
                            s = _parse_dt(slot.start)
                            e = s + timedelta(minutes=task.duration_minutes)
                            scheduled.append(ScheduledItem(task_name=task.name, start=_fmt_dt(s), end=_fmt_dt(e), priority=task.priority))
                            booked.append((s, e))
                            placed = True
                            break
                current_day += timedelta(days=1)
            if not placed:
                unscheduled.append(task.name)

        logger.info(f"批量优化: {len(scheduled)} 已安排, {len(unscheduled)} 未安排")
        return {
            "status": "success", "total_tasks": len(sorted_tasks),
            "scheduled_count": len(scheduled), "unscheduled_count": len(unscheduled),
            "scheduled_items": [i.to_dict() for i in scheduled],
            "unscheduled_tasks": unscheduled,
        }

    async def _handle_optimize_schedule(self, params: dict[str, Any]) -> dict[str, Any]:
        tasks = params.get("tasks", [])
        if not tasks:
            return {"error": "缺少必要参数: tasks"}
        return await self.optimize_schedule(tasks)

    # ------------------------------------------------------------------
    # 冲突检测
    # ------------------------------------------------------------------

    async def detect_conflicts(self, new_events: list[dict[str, Any]]) -> dict[str, Any]:
        """检测新事件与已有日程的冲突。"""
        if not new_events:
            return {"error": "事件列表为空"}
        starts, ends = [], []
        for raw in new_events:
            try:
                starts.append(_parse_dt(raw["start"]))
                ends.append(_parse_dt(raw["end"]))
            except (KeyError, ValueError):
                continue
        if not starts:
            return {"error": "没有包含有效时间的事件"}

        existing = await self._fetch_events(min(starts) - timedelta(hours=1), max(ends) + timedelta(hours=1))
        conflicts: list[ConflictInfo] = []
        no_conflict: list[str] = []

        for raw in new_events:
            name = raw.get("name") or raw.get("task_name", "未命名事件")
            try:
                ns, ne = _parse_dt(raw["start"]), _parse_dt(raw["end"])
            except (KeyError, ValueError):
                conflicts.append(ConflictInfo(new_event=name, existing_event="(解析失败)", suggestion="时间格式不正确"))
                continue
            if ne <= ns:
                conflicts.append(ConflictInfo(new_event=name, existing_event="(无效时间)", suggestion="结束时间必须晚于开始时间"))
                continue

            found = False
            for evt in existing:
                if not evt.is_blocking:
                    continue
                try:
                    es, ee = _parse_dt(evt.start), _parse_dt(evt.end)
                except (ValueError, TypeError):
                    continue
                os, oe = max(ns, es), min(ne, ee)
                if os < oe:
                    found = True
                    conflicts.append(ConflictInfo(
                        new_event=name, existing_event=evt.subject or "(无标题)",
                        overlap_start=_fmt_dt(os), overlap_end=_fmt_dt(oe),
                        suggestion=self._suggest_resolution(name, ns, ne, existing),
                    ))
            if not found:
                no_conflict.append(name)

        return {
            "status": "success", "total_checked": len(new_events),
            "conflict_count": len(conflicts), "no_conflict_count": len(no_conflict),
            "conflicts": [c.to_dict() for c in conflicts], "no_conflict_events": no_conflict,
        }

    async def _handle_detect_conflicts(self, params: dict[str, Any]) -> dict[str, Any]:
        events = params.get("new_events", [])
        if not events:
            return {"error": "缺少必要参数: new_events"}
        return await self.detect_conflicts(events)

    # ------------------------------------------------------------------
    # 每日计划生成
    # ------------------------------------------------------------------

    async def generate_daily_plan(
        self, date: str | None = None, pending_tasks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """生成每日计划。"""
        try:
            target = _parse_dt(date) if date else datetime.now()
        except ValueError as e:
            return {"error": str(e)}

        day_str = target.strftime("%Y-%m-%d")
        day_ws = target.replace(hour=self._config.work_start_hour, minute=0, second=0, microsecond=0)
        day_we = target.replace(hour=self._config.work_end_hour, minute=0, second=0, microsecond=0)

        events = await self._fetch_events(day_ws, day_we)
        free_slots = _compute_free_slots(day_ws, day_we, events, self._config)

        items: list[ScheduledItem] = []
        unscheduled: list[str] = []

        if pending_tasks:
            parsed = _sort_tasks([t for raw in pending_tasks if (t := _parse_task(raw)) is not None])
            remaining = list(free_slots)
            for task in parsed:
                placed = False
                for i, slot in enumerate(remaining):
                    if slot.duration_minutes >= task.duration_minutes:
                        s = _parse_dt(slot.start)
                        e = s + timedelta(minutes=task.duration_minutes)
                        items.append(ScheduledItem(task_name=task.name, start=_fmt_dt(s), end=_fmt_dt(e), priority=task.priority))
                        ns = e + timedelta(minutes=self._config.break_between_tasks)
                        se = _parse_dt(slot.end)
                        remaining[i] = TimeSlot(start=_fmt_dt(ns), end=slot.end, duration_minutes=max(0, int((se - ns).total_seconds() / 60))) if ns < se else TimeSlot(start=slot.end, end=slot.end, duration_minutes=0)
                        placed = True
                        break
                if not placed:
                    unscheduled.append(task.name)

        existing_min = sum(int((_parse_dt(e.end) - _parse_dt(e.start)).total_seconds() / 60) for e in events if e.is_blocking and e.start and e.end) if events else 0
        free_min = sum(s.duration_minutes for s in free_slots)
        sched_min = sum(int((_parse_dt(it.end) - _parse_dt(it.start)).total_seconds() / 60) for it in items)

        plan = DailyPlan(
            date=day_str, scheduled_items=items, existing_events=events,
            free_slots=free_slots, unscheduled_tasks=unscheduled,
            summary=f"{day_str}: 已有 {len(events)} 个日程({existing_min}分钟), 空闲 {len(free_slots)} 段({free_min}分钟), 新安排 {len(items)} 个({sched_min}分钟), 未安排 {len(unscheduled)} 个",
        )
        return {"status": "success", **plan.to_dict()}

    async def _handle_generate_daily_plan(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.generate_daily_plan(params.get("date"), params.get("pending_tasks"))

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    async def _fetch_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        """从 calendar_ops 获取已有日程。"""
        if self._calendar_ops is None:
            return []
        try:
            result = await self._calendar_ops.execute("list_events", {"start_date": _fmt_dt(start), "end_date": _fmt_dt(end)})
        except Exception as e:
            logger.warning(f"获取日历数据失败: {e}")
            return []
        if "error" in result:
            return []
        return [CalendarEvent(
            event_id=r.get("event_id", ""), subject=r.get("subject", ""),
            start=r.get("start", ""), end=r.get("end", ""),
            location=r.get("location", ""), busy_status=r.get("busy_status", "busy"),
        ) for r in result.get("events", [])]

    @staticmethod
    def _filter_events_for_day(events: list[CalendarEvent], day: datetime) -> list[CalendarEvent]:
        """过滤出某天的事件。"""
        ds = day.strftime("%Y-%m-%d")
        return [e for e in events if e.start.startswith(ds)]

    def _suggest_resolution(self, name: str, start: datetime, end: datetime, existing: list[CalendarEvent]) -> str:
        """为冲突生成调整建议。"""
        dur = int((end - start).total_seconds() / 60)
        search = end
        for _ in range(7):
            candidate = _next_work_time(search, self._config)
            ce = candidate + timedelta(minutes=dur)
            ok = True
            for evt in existing:
                if not evt.is_blocking:
                    continue
                try:
                    if max(candidate, _parse_dt(evt.start)) < min(ce, _parse_dt(evt.end)):
                        ok = False
                        break
                except (ValueError, TypeError):
                    continue
            if ok:
                return f"建议将 '{name}' 调整到 {_fmt_dt(candidate)} - {_fmt_dt(ce)}"
            search = ce + timedelta(days=1)
        return "冲突较密集，建议手动调整或重新安排优先级"
