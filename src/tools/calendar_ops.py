"""日程管理工具集。

提供日历事件查看、创建、修改、删除及忙闲查询能力。
基于 Windows Outlook COM 接口 (win32com.client) 实现。
"""

from __future__ import annotations

import asyncio
import platform
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# COM 可用性检测
# ---------------------------------------------------------------------------

_com_available: bool = False
_com_checked: bool = False


def _check_com_available() -> bool:
    """检测 win32com 是否可用（仅 Windows + 已安装 Outlook）。"""
    global _com_available, _com_checked
    if _com_checked:
        return _com_available
    _com_checked = True
    if platform.system() != "Windows":
        logger.debug("非 Windows 平台，Outlook COM 不可用")
        return False
    try:
        import win32com.client  # noqa: F401
        _com_available = True
    except ImportError:
        logger.debug("win32com 未安装，Outlook COM 不可用")
    return _com_available


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# Outlook OlDefaultFolders 枚举
_OL_FOLDER_CALENDAR = 9

# Outlook OlBusyStatus 枚举
_BUSY_STATUS_MAP: dict[int, str] = {
    0: "free",
    1: "tentative",
    2: "busy",
    3: "out_of_office",
}

# 默认查询天数
_DEFAULT_RANGE_DAYS = 7


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------

def _require_params(params: dict[str, Any], required: list[str]) -> list[str]:
    """返回缺失的必要参数名列表。"""
    return [k for k in required if k not in params or params[k] is None]


def _parse_datetime(value: str) -> datetime:
    """解析日期时间字符串，支持多种格式。

    接受 ``YYYY-MM-DD``、``YYYY-MM-DD HH:MM``、ISO 8601 等。
    无时区信息时默认使用本地时区。
    """
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(
        f"无法解析日期时间: '{value}'，支持格式: YYYY-MM-DD [HH:MM[:SS]]"
    )


# ---------------------------------------------------------------------------
# COM 辅助
# ---------------------------------------------------------------------------

def _get_outlook_app() -> Any:
    """获取 Outlook Application COM 对象。"""
    import win32com.client
    try:
        return win32com.client.GetActiveObject("Outlook.Application")
    except Exception:
        return win32com.client.Dispatch("Outlook.Application")


def _get_calendar_folder(outlook: Any) -> Any:
    """获取默认日历文件夹。"""
    namespace = outlook.GetNamespace("MAPI")
    return namespace.GetDefaultFolder(_OL_FOLDER_CALENDAR)


def _com_dt(dt: datetime) -> Any:
    """Python datetime → COM 日期（去掉时区信息，COM 使用本地时间）。"""
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz=None).replace(tzinfo=None)
    return dt.strftime("%m/%d/%Y %H:%M %p")


def _parse_com_dt(com_value: Any) -> str:
    """COM 日期值 → ISO 格式字符串。"""
    if com_value is None:
        return ""
    try:
        # pywin32 返回的通常是 datetime 对象
        if isinstance(com_value, datetime):
            return com_value.strftime("%Y-%m-%d %H:%M")
        return str(com_value)
    except Exception:
        return str(com_value)


def _event_to_dict(item: Any) -> dict[str, Any]:
    """将 Outlook AppointmentItem 转为可序列化字典。"""
    return {
        "event_id": item.EntryID,
        "subject": item.Subject or "",
        "start": _parse_com_dt(item.Start),
        "end": _parse_com_dt(item.End),
        "location": item.Location or "",
        "body": item.Body[:500] if item.Body else "",
        "busy_status": _BUSY_STATUS_MAP.get(item.BusyStatus, "unknown"),
        "reminder_minutes": item.ReminderMinutesBeforeStart if item.ReminderSet else None,
        "is_recurring": item.IsRecurring,
    }


# ---------------------------------------------------------------------------
# 同步操作（在 to_thread 中运行）
# ---------------------------------------------------------------------------

def _sync_list_events(start: datetime, end: datetime) -> dict[str, Any]:
    """同步查询日程。"""
    outlook = _get_outlook_app()
    folder = _get_calendar_folder(outlook)
    items = folder.Items

    # 按 Start 排序
    items.Sort("[Start]")
    items.IncludeRecurrences = True

    # 筛选范围
    restriction = (
        f"[Start] <= '{_com_dt(end)}' AND [End] >= '{_com_dt(start)}'"
    )
    items = items.Restrict(restriction)

    events: list[dict[str, Any]] = []
    count = 0
    max_results = 200
    for item in items:
        try:
            events.append(_event_to_dict(item))
            count += 1
            if count >= max_results:
                break
        except Exception as e:
            logger.warning(f"跳过无法读取的日程项: {e}")
            continue

    return {"events": events, "count": len(events)}


def _sync_create_event(
    subject: str,
    start: datetime,
    end: datetime,
    location: str,
    body: str,
    reminder_minutes: int | None,
) -> dict[str, Any]:
    """同步创建日程。"""
    outlook = _get_outlook_app()
    namespace = outlook.GetNamespace("MAPI")
    calendar = namespace.GetDefaultFolder(_OL_FOLDER_CALENDAR)

    appointment = calendar.Items.Add(1)  # olAppointmentItem = 1
    appointment.Subject = subject
    appointment.Start = _com_dt(start)
    appointment.End = _com_dt(end)

    if location:
        appointment.Location = location
    if body:
        appointment.Body = body
    if reminder_minutes is not None:
        appointment.ReminderSet = True
        appointment.ReminderMinutesBeforeStart = reminder_minutes
    else:
        appointment.ReminderSet = False

    appointment.Save()

    return {
        "event_id": appointment.EntryID,
        "subject": appointment.Subject,
        "start": _parse_com_dt(appointment.Start),
        "end": _parse_com_dt(appointment.End),
        "message": "日程创建成功",
    }


def _sync_update_event(event_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """同步修改日程。"""
    outlook = _get_outlook_app()
    namespace = outlook.GetNamespace("MAPI")

    # 通过 EntryID 查找
    item = namespace.GetItemFromID(event_id)
    if item is None:
        return {"error": f"未找到日程: {event_id}"}

    changed_fields: list[str] = []

    if "subject" in updates and updates["subject"] is not None:
        item.Subject = updates["subject"]
        changed_fields.append("subject")
    if "start_time" in updates and updates["start_time"] is not None:
        item.Start = _com_dt(_parse_datetime(updates["start_time"]))
        changed_fields.append("start_time")
    if "end_time" in updates and updates["end_time"] is not None:
        item.End = _com_dt(_parse_datetime(updates["end_time"]))
        changed_fields.append("end_time")
    if "location" in updates and updates["location"] is not None:
        item.Location = updates["location"]
        changed_fields.append("location")
    if "body" in updates and updates["body"] is not None:
        item.Body = updates["body"]
        changed_fields.append("body")
    if "reminder_minutes" in updates and updates["reminder_minutes"] is not None:
        item.ReminderSet = True
        item.ReminderMinutesBeforeStart = int(updates["reminder_minutes"])
        changed_fields.append("reminder_minutes")

    item.Save()

    return {
        "event_id": event_id,
        "changed_fields": changed_fields,
        "message": "日程更新成功",
    }


def _sync_delete_event(event_id: str) -> dict[str, Any]:
    """同步删除日程。"""
    outlook = _get_outlook_app()
    namespace = outlook.GetNamespace("MAPI")

    item = namespace.GetItemFromID(event_id)
    if item is None:
        return {"error": f"未找到日程: {event_id}"}

    subject = item.Subject
    item.Delete()

    return {
        "event_id": event_id,
        "subject": subject,
        "message": "日程删除成功",
    }


def _sync_check_freebusy(start: datetime, end: datetime) -> dict[str, Any]:
    """同步查询忙闲状态。

    通过获取指定范围内的所有事件来判断忙闲。
    """
    outlook = _get_outlook_app()
    folder = _get_calendar_folder(outlook)
    items = folder.Items

    items.Sort("[Start]")
    items.IncludeRecurrences = True

    restriction = (
        f"[Start] < '{_com_dt(end)}' AND [End] > '{_com_dt(start)}'"
    )
    items = items.Restrict(restriction)

    busy_periods: list[dict[str, str]] = []
    for item in items:
        try:
            busy_periods.append({
                "subject": item.Subject or "(无标题)",
                "start": _parse_com_dt(item.Start),
                "end": _parse_com_dt(item.End),
                "busy_status": _BUSY_STATUS_MAP.get(item.BusyStatus, "unknown"),
            })
        except Exception:
            continue

    is_free = len(busy_periods) == 0
    return {
        "start": start.strftime("%Y-%m-%d %H:%M"),
        "end": end.strftime("%Y-%m-%d %H:%M"),
        "is_free": is_free,
        "busy_periods": busy_periods,
        "message": "空闲" if is_free else f"有 {len(busy_periods)} 个日程冲突",
    }


# ---------------------------------------------------------------------------
# CalendarOps 主类
# ---------------------------------------------------------------------------

class CalendarOps:
    """日程管理工具集。

    通过 Outlook COM 接口实现日历操作，支持查看、创建、修改、删除日程及忙闲查询。

    Usage::

        cal = CalendarOps()
        # 查看本周日程
        result = await cal.execute("list_events", {
            "start_date": "2025-01-01",
            "end_date": "2025-01-07",
        })
    """

    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = workspace
        self._com_available: bool | None = None

    def _ensure_com(self) -> dict[str, Any] | None:
        """检查 COM 可用性，不可用时返回错误字典。"""
        if self._com_available is None:
            self._com_available = _check_com_available()
        if not self._com_available:
            return {
                "error": (
                    "日程管理功能需要 Windows 平台并安装 Microsoft Outlook。"
                    "请确认：1) 当前系统为 Windows；2) 已安装 Outlook 桌面版。"
                ),
            }
        return None

    async def execute(self, action: str, params: dict[str, Any]) -> Any:
        """执行日程管理操作。

        Args:
            action: 操作类型
            params: 操作参数

        Returns:
            操作结果字典
        """
        handlers: dict[str, Any] = {
            "list_events": self._list_events,
            "create_event": self._create_event,
            "update_event": self._update_event,
            "delete_event": self._delete_event,
            "check_freebusy": self._check_freebusy,
        }

        handler = handlers.get(action)
        if handler is None:
            logger.error(f"未知日程操作: {action}")
            return {
                "error": f"未知操作: {action}",
                "available_actions": sorted(handlers.keys()),
            }

        return await handler(params)

    # ------------------------------------------------------------------
    # 查看日程
    # ------------------------------------------------------------------

    async def _list_events(self, params: dict[str, Any]) -> dict[str, Any]:
        """查询指定日期范围内的日历事件。

        Params:
            start_date: 开始日期（可选，默认今天）
            end_date: 结束日期（可选，默认 start_date + 7天）
        """
        com_err = self._ensure_com()
        if com_err:
            return com_err

        try:
            start = (
                _parse_datetime(params["start_date"])
                if "start_date" in params and params["start_date"]
                else datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            )
            end = (
                _parse_datetime(params["end_date"])
                if "end_date" in params and params["end_date"]
                else start + timedelta(days=_DEFAULT_RANGE_DAYS)
            )
        except ValueError as e:
            return {"error": str(e)}

        try:
            return await asyncio.to_thread(_sync_list_events, start, end)
        except Exception as e:
            logger.error(f"查询日程失败: {e}")
            return {"error": f"查询日程失败: {e}"}

    # ------------------------------------------------------------------
    # 创建日程
    # ------------------------------------------------------------------

    async def _create_event(self, params: dict[str, Any]) -> dict[str, Any]:
        """创建新的日历事件。

        Params:
            subject: 日程标题（必填）
            start_time: 开始时间，格式 YYYY-MM-DD HH:MM（必填）
            end_time: 结束时间，格式 YYYY-MM-DD HH:MM（必填）
            location: 地点（可选）
            body: 描述/备注（可选）
            reminder_minutes: 提前多少分钟提醒（可选，如 15）
        """
        com_err = self._ensure_com()
        if com_err:
            return com_err

        missing = _require_params(params, ["subject", "start_time", "end_time"])
        if missing:
            return {"error": f"缺少必要参数: {', '.join(missing)}"}

        try:
            start = _parse_datetime(params["start_time"])
            end = _parse_datetime(params["end_time"])
        except ValueError as e:
            return {"error": str(e)}

        if end <= start:
            return {"error": "结束时间必须晚于开始时间"}

        subject = params["subject"]
        location = params.get("location", "")
        body = params.get("body", "")
        reminder = params.get("reminder_minutes")
        if reminder is not None:
            try:
                reminder = int(reminder)
            except (ValueError, TypeError):
                return {"error": "reminder_minutes 必须为整数"}

        try:
            return await asyncio.to_thread(
                _sync_create_event, subject, start, end, location, body, reminder
            )
        except Exception as e:
            logger.error(f"创建日程失败: {e}")
            return {"error": f"创建日程失败: {e}"}

    # ------------------------------------------------------------------
    # 修改日程
    # ------------------------------------------------------------------

    async def _update_event(self, params: dict[str, Any]) -> dict[str, Any]:
        """修改已有日历事件。

        Params:
            event_id: 日程 ID（必填，EntryID 格式）
            subject: 新标题（可选）
            start_time: 新开始时间（可选）
            end_time: 新结束时间（可选）
            location: 新地点（可选）
            body: 新描述（可选）
            reminder_minutes: 新提醒时间（可选）
        """
        com_err = self._ensure_com()
        if com_err:
            return com_err

        missing = _require_params(params, ["event_id"])
        if missing:
            return {"error": f"缺少必要参数: {', '.join(missing)}"}

        # 检查是否至少有一个更新字段
        update_fields = [
            "subject", "start_time", "end_time",
            "location", "body", "reminder_minutes",
        ]
        if not any(k in params for k in update_fields):
            return {"error": "请至少提供一个要更新的字段"}

        # 预校验日期格式
        for dt_field in ("start_time", "end_time"):
            if dt_field in params and params[dt_field] is not None:
                try:
                    _parse_datetime(params[dt_field])
                except ValueError as e:
                    return {"error": str(e)}

        try:
            return await asyncio.to_thread(
                _sync_update_event, params["event_id"], params
            )
        except Exception as e:
            logger.error(f"修改日程失败: {e}")
            return {"error": f"修改日程失败: {e}"}

    # ------------------------------------------------------------------
    # 删除日程
    # ------------------------------------------------------------------

    async def _delete_event(self, params: dict[str, Any]) -> dict[str, Any]:
        """删除指定日历事件。

        Params:
            event_id: 日程 ID（必填）
        """
        com_err = self._ensure_com()
        if com_err:
            return com_err

        missing = _require_params(params, ["event_id"])
        if missing:
            return {"error": f"缺少必要参数: {', '.join(missing)}"}

        try:
            return await asyncio.to_thread(
                _sync_delete_event, params["event_id"]
            )
        except Exception as e:
            logger.error(f"删除日程失败: {e}")
            return {"error": f"删除日程失败: {e}"}

    # ------------------------------------------------------------------
    # 查询忙闲
    # ------------------------------------------------------------------

    async def _check_freebusy(self, params: dict[str, Any]) -> dict[str, Any]:
        """查看某个时间段是否空闲。

        Params:
            start_time: 开始时间（可选，默认当前）
            end_time: 结束时间（可选，默认 start + 1小时）
        """
        com_err = self._ensure_com()
        if com_err:
            return com_err

        try:
            start = (
                _parse_datetime(params["start_time"])
                if "start_time" in params and params["start_time"]
                else datetime.now()
            )
            end = (
                _parse_datetime(params["end_time"])
                if "end_time" in params and params["end_time"]
                else start + timedelta(hours=1)
            )
        except ValueError as e:
            return {"error": str(e)}

        if end <= start:
            return {"error": "结束时间必须晚于开始时间"}

        try:
            return await asyncio.to_thread(_sync_check_freebusy, start, end)
        except Exception as e:
            logger.error(f"查询忙闲失败: {e}")
            return {"error": f"查询忙闲失败: {e}"}
