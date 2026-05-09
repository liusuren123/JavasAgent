"""CalendarOps 日程管理工具测试。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.tools.calendar_ops import (
    CalendarOps,
    _BUSY_STATUS_MAP,
    _com_dt,
    _event_to_dict,
    _parse_com_dt,
    _parse_datetime,
    _require_params,
)


# ======================================================================
# 辅助
# ======================================================================


@pytest.fixture
def cal_ops() -> CalendarOps:
    """创建 CalendarOps 实例。"""
    return CalendarOps()


def _make_mock_appointment(
    entry_id: str = "ENTRY001",
    subject: str = "测试会议",
    start: datetime | None = None,
    end: datetime | None = None,
    location: str = "会议室A",
    body: str = "会议内容",
    busy_status: int = 2,
    reminder_set: bool = True,
    reminder_minutes: int = 15,
    is_recurring: bool = False,
) -> MagicMock:
    """创建模拟的 Outlook AppointmentItem。"""
    item = MagicMock()
    item.EntryID = entry_id
    item.Subject = subject
    item.Start = start or datetime(2025, 6, 1, 10, 0)
    item.End = end or datetime(2025, 6, 1, 11, 0)
    item.Location = location
    item.Body = body
    item.BusyStatus = busy_status
    item.ReminderSet = reminder_set
    item.ReminderMinutesBeforeStart = reminder_minutes
    item.IsRecurring = is_recurring
    return item


# ======================================================================
# 参数解析
# ======================================================================


class TestParamParsing:
    """参数解析和校验测试。"""

    def test_require_params_all_present(self) -> None:
        assert _require_params({"a": 1, "b": 2}, ["a", "b"]) == []

    def test_require_params_missing(self) -> None:
        result = _require_params({"a": 1}, ["a", "b", "c"])
        assert "b" in result
        assert "c" in result

    def test_require_params_none_value(self) -> None:
        result = _require_params({"a": None, "b": 1}, ["a", "b"])
        assert "a" in result
        assert "b" not in result

    def test_parse_datetime_iso(self) -> None:
        dt = _parse_datetime("2025-06-01T10:30:00")
        assert dt.year == 2025 and dt.month == 6 and dt.day == 1

    def test_parse_datetime_with_space(self) -> None:
        dt = _parse_datetime("2025-06-01 10:30")
        assert dt.hour == 10 and dt.minute == 30

    def test_parse_datetime_date_only(self) -> None:
        dt = _parse_datetime("2025-06-01")
        assert dt.hour == 0 and dt.minute == 0

    def test_parse_datetime_full_seconds(self) -> None:
        dt = _parse_datetime("2025-06-01 10:30:45")
        assert dt.second == 45

    def test_parse_datetime_invalid(self) -> None:
        with pytest.raises(ValueError, match="无法解析日期时间"):
            _parse_datetime("not-a-date")

    def test_parse_com_dt_with_datetime(self) -> None:
        result = _parse_com_dt(datetime(2025, 6, 1, 10, 30))
        assert result == "2025-06-01 10:30"

    def test_parse_com_dt_none(self) -> None:
        assert _parse_com_dt(None) == ""

    def test_com_dt_basic(self) -> None:
        dt = datetime(2025, 6, 1, 10, 0)
        result = _com_dt(dt)
        assert "06/01/2025" in result

    def test_event_to_dict(self) -> None:
        item = _make_mock_appointment()
        result = _event_to_dict(item)
        assert result["event_id"] == "ENTRY001"
        assert result["subject"] == "测试会议"
        assert result["location"] == "会议室A"
        assert result["busy_status"] == "busy"
        assert result["is_recurring"] is False

    def test_event_to_dict_no_reminder(self) -> None:
        item = _make_mock_appointment(reminder_set=False)
        result = _event_to_dict(item)
        assert result["reminder_minutes"] is None


# ======================================================================
# 初始化 & 错误处理
# ======================================================================


class TestCalendarOpsInit:
    """初始化和通用测试。"""

    def test_default_init(self) -> None:
        ops = CalendarOps()
        assert ops._workspace is None

    def test_init_with_workspace(self) -> None:
        ops = CalendarOps(workspace="/tmp/test")
        assert ops._workspace == "/tmp/test"

    @pytest.mark.asyncio
    async def test_unknown_action(self, cal_ops: CalendarOps) -> None:
        result = await cal_ops.execute("nonexistent", {})
        assert "error" in result
        assert "available_actions" in result
        expected_actions = ["list_events", "create_event", "update_event",
                            "delete_event", "check_freebusy"]
        for a in expected_actions:
            assert a in result["available_actions"]


# ======================================================================
# COM 不可用降级
# ======================================================================


class TestCOMUnavailable:
    """COM 不可用时的降级测试。"""

    @pytest.mark.asyncio
    async def test_list_events_no_com(self) -> None:
        ops = CalendarOps()
        ops._com_available = False
        result = await ops.execute("list_events", {})
        assert "error" in result
        assert "Outlook" in result["error"]

    @pytest.mark.asyncio
    async def test_create_event_no_com(self) -> None:
        ops = CalendarOps()
        ops._com_available = False
        result = await ops.execute("create_event", {
            "subject": "测试",
            "start_time": "2025-06-01 10:00",
            "end_time": "2025-06-01 11:00",
        })
        assert "error" in result
        assert "Outlook" in result["error"]

    @pytest.mark.asyncio
    async def test_update_event_no_com(self) -> None:
        ops = CalendarOps()
        ops._com_available = False
        result = await ops.execute("update_event", {"event_id": "abc"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_delete_event_no_com(self) -> None:
        ops = CalendarOps()
        ops._com_available = False
        result = await ops.execute("delete_event", {"event_id": "abc"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_check_freebusy_no_com(self) -> None:
        ops = CalendarOps()
        ops._com_available = False
        result = await ops.execute("check_freebusy", {})
        assert "error" in result


# ======================================================================
# 查看日程 (list_events)
# ======================================================================


class TestListEvents:
    """查看日程测试。"""

    @pytest.mark.asyncio
    async def test_list_events_success(self) -> None:
        mock_item = _make_mock_appointment()
        mock_restricted = MagicMock()
        mock_restricted.__iter__ = lambda self: iter([mock_item])

        mock_items = MagicMock()
        mock_items.Restrict.return_value = mock_restricted

        mock_folder = MagicMock()
        mock_folder.Items = mock_items

        with patch("src.tools.calendar_ops._get_calendar_folder", return_value=mock_folder), \
             patch("src.tools.calendar_ops._get_outlook_app"):
            ops = CalendarOps()
            ops._com_available = True
            result = await ops.execute("list_events", {
                "start_date": "2025-06-01",
                "end_date": "2025-06-07",
            })

        assert "events" in result
        assert result["count"] == 1
        assert result["events"][0]["subject"] == "测试会议"

    @pytest.mark.asyncio
    async def test_list_events_empty(self) -> None:
        mock_restricted = MagicMock()
        mock_restricted.__iter__ = lambda self: iter([])

        mock_items = MagicMock()
        mock_items.Restrict.return_value = mock_restricted

        mock_folder = MagicMock()
        mock_folder.Items = mock_items

        with patch("src.tools.calendar_ops._get_calendar_folder", return_value=mock_folder), \
             patch("src.tools.calendar_ops._get_outlook_app"):
            ops = CalendarOps()
            ops._com_available = True
            result = await ops.execute("list_events", {})
            assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_list_events_invalid_date(self) -> None:
        ops = CalendarOps()
        ops._com_available = True
        result = await ops.execute("list_events", {
            "start_date": "invalid-date",
        })
        assert "error" in result


# ======================================================================
# 创建日程 (create_event)
# ======================================================================


class TestCreateEvent:
    """创建日程测试。"""

    @pytest.mark.asyncio
    async def test_create_event_missing_subject(self) -> None:
        ops = CalendarOps()
        ops._com_available = True
        result = await ops.execute("create_event", {
            "start_time": "2025-06-01 10:00",
            "end_time": "2025-06-01 11:00",
        })
        assert "error" in result
        assert "subject" in result["error"]

    @pytest.mark.asyncio
    async def test_create_event_missing_time(self) -> None:
        ops = CalendarOps()
        ops._com_available = True
        result = await ops.execute("create_event", {
            "subject": "测试会议",
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_create_event_end_before_start(self) -> None:
        ops = CalendarOps()
        ops._com_available = True
        result = await ops.execute("create_event", {
            "subject": "测试",
            "start_time": "2025-06-01 11:00",
            "end_time": "2025-06-01 10:00",
        })
        assert "error" in result
        assert "结束时间" in result["error"]

    @pytest.mark.asyncio
    async def test_create_event_invalid_date(self) -> None:
        ops = CalendarOps()
        ops._com_available = True
        result = await ops.execute("create_event", {
            "subject": "测试",
            "start_time": "bad",
            "end_time": "2025-06-01 11:00",
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_create_event_invalid_reminder(self) -> None:
        ops = CalendarOps()
        ops._com_available = True
        result = await ops.execute("create_event", {
            "subject": "测试",
            "start_time": "2025-06-01 10:00",
            "end_time": "2025-06-01 11:00",
            "reminder_minutes": "not-a-number",
        })
        assert "error" in result
        assert "reminder_minutes" in result["error"]

    @pytest.mark.asyncio
    async def test_create_event_success(self) -> None:
        mock_appointment = MagicMock()
        mock_appointment.EntryID = "NEW001"
        mock_appointment.Subject = "新建会议"
        mock_appointment.Start = datetime(2025, 6, 1, 10, 0)
        mock_appointment.End = datetime(2025, 6, 1, 11, 0)

        mock_folder = MagicMock()
        mock_folder.Items.Add.return_value = mock_appointment

        with patch("src.tools.calendar_ops._get_calendar_folder", return_value=mock_folder), \
             patch("src.tools.calendar_ops._get_outlook_app") as mock_get_app:
            mock_namespace = MagicMock()
            mock_get_app.return_value.GetNamespace.return_value = mock_namespace
            mock_namespace.GetDefaultFolder.return_value = mock_folder

            ops = CalendarOps()
            ops._com_available = True
            result = await ops.execute("create_event", {
                "subject": "新建会议",
                "start_time": "2025-06-01 10:00",
                "end_time": "2025-06-01 11:00",
                "location": "3楼会议室",
                "body": "讨论项目进展",
                "reminder_minutes": 30,
            })

        assert "event_id" in result
        assert result["message"] == "日程创建成功"
        mock_appointment.Save.assert_called_once()


# ======================================================================
# 修改日程 (update_event)
# ======================================================================


class TestUpdateEvent:
    """修改日程测试。"""

    @pytest.mark.asyncio
    async def test_update_event_missing_id(self) -> None:
        ops = CalendarOps()
        ops._com_available = True
        result = await ops.execute("update_event", {"subject": "新标题"})
        assert "error" in result
        assert "event_id" in result["error"]

    @pytest.mark.asyncio
    async def test_update_event_no_update_fields(self) -> None:
        ops = CalendarOps()
        ops._com_available = True
        result = await ops.execute("update_event", {"event_id": "ENTRY001"})
        assert "error" in result
        assert "field" in result["error"].lower() or "字段" in result["error"]

    @pytest.mark.asyncio
    async def test_update_event_invalid_start_time(self) -> None:
        ops = CalendarOps()
        ops._com_available = True
        result = await ops.execute("update_event", {
            "event_id": "ENTRY001",
            "start_time": "invalid",
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_update_event_success(self) -> None:
        mock_item = _make_mock_appointment(entry_id="ENTRY001")

        with patch("src.tools.calendar_ops._get_outlook_app") as mock_get_app:
            mock_namespace = MagicMock()
            mock_namespace.GetItemFromID.return_value = mock_item
            mock_get_app.return_value.GetNamespace.return_value = mock_namespace

            ops = CalendarOps()
            ops._com_available = True
            result = await ops.execute("update_event", {
                "event_id": "ENTRY001",
                "subject": "更新后的标题",
                "location": "新会议室",
            })

        assert result["message"] == "日程更新成功"
        assert "subject" in result["changed_fields"]
        assert "location" in result["changed_fields"]
        mock_item.Save.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_event_not_found(self) -> None:
        with patch("src.tools.calendar_ops._get_outlook_app") as mock_get_app:
            mock_namespace = MagicMock()
            mock_namespace.GetItemFromID.return_value = None
            mock_get_app.return_value.GetNamespace.return_value = mock_namespace

            ops = CalendarOps()
            ops._com_available = True
            result = await ops.execute("update_event", {
                "event_id": "NOTEXIST",
                "subject": "新标题",
            })

        assert "error" in result


# ======================================================================
# 删除日程 (delete_event)
# ======================================================================


class TestDeleteEvent:
    """删除日程测试。"""

    @pytest.mark.asyncio
    async def test_delete_event_missing_id(self) -> None:
        ops = CalendarOps()
        ops._com_available = True
        result = await ops.execute("delete_event", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_delete_event_success(self) -> None:
        mock_item = _make_mock_appointment(entry_id="DEL001", subject="待删除")

        with patch("src.tools.calendar_ops._get_outlook_app") as mock_get_app:
            mock_namespace = MagicMock()
            mock_namespace.GetItemFromID.return_value = mock_item
            mock_get_app.return_value.GetNamespace.return_value = mock_namespace

            ops = CalendarOps()
            ops._com_available = True
            result = await ops.execute("delete_event", {"event_id": "DEL001"})

        assert result["message"] == "日程删除成功"
        assert result["subject"] == "待删除"
        mock_item.Delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_event_not_found(self) -> None:
        with patch("src.tools.calendar_ops._get_outlook_app") as mock_get_app:
            mock_namespace = MagicMock()
            mock_namespace.GetItemFromID.return_value = None
            mock_get_app.return_value.GetNamespace.return_value = mock_namespace

            ops = CalendarOps()
            ops._com_available = True
            result = await ops.execute("delete_event", {"event_id": "NOTEXIST"})

        assert "error" in result


# ======================================================================
# 查询忙闲 (check_freebusy)
# ======================================================================


class TestCheckFreebusy:
    """忙闲查询测试。"""

    @pytest.mark.asyncio
    async def test_check_freebusy_free(self) -> None:
        mock_restricted = MagicMock()
        mock_restricted.__iter__ = lambda self: iter([])

        mock_items = MagicMock()
        mock_items.Restrict.return_value = mock_restricted

        mock_folder = MagicMock()
        mock_folder.Items = mock_items

        with patch("src.tools.calendar_ops._get_calendar_folder", return_value=mock_folder), \
             patch("src.tools.calendar_ops._get_outlook_app"):
            ops = CalendarOps()
            ops._com_available = True
            result = await ops.execute("check_freebusy", {
                "start_time": "2025-06-01 10:00",
                "end_time": "2025-06-01 11:00",
            })

        assert result["is_free"] is True
        assert result["busy_periods"] == []

    @pytest.mark.asyncio
    async def test_check_freebusy_busy(self) -> None:
        mock_item = _make_mock_appointment()
        mock_restricted = MagicMock()
        mock_restricted.__iter__ = lambda self: iter([mock_item])

        mock_items = MagicMock()
        mock_items.Restrict.return_value = mock_restricted

        mock_folder = MagicMock()
        mock_folder.Items = mock_items

        with patch("src.tools.calendar_ops._get_calendar_folder", return_value=mock_folder), \
             patch("src.tools.calendar_ops._get_outlook_app"):
            ops = CalendarOps()
            ops._com_available = True
            result = await ops.execute("check_freebusy", {
                "start_time": "2025-06-01 09:00",
                "end_time": "2025-06-01 12:00",
            })

        assert result["is_free"] is False
        assert len(result["busy_periods"]) == 1

    @pytest.mark.asyncio
    async def test_check_freebusy_default_range(self) -> None:
        mock_restricted = MagicMock()
        mock_restricted.__iter__ = lambda self: iter([])

        mock_items = MagicMock()
        mock_items.Restrict.return_value = mock_restricted

        mock_folder = MagicMock()
        mock_folder.Items = mock_items

        with patch("src.tools.calendar_ops._get_calendar_folder", return_value=mock_folder), \
             patch("src.tools.calendar_ops._get_outlook_app"):
            ops = CalendarOps()
            ops._com_available = True
            result = await ops.execute("check_freebusy", {})
            assert "is_free" in result

    @pytest.mark.asyncio
    async def test_check_freebusy_end_before_start(self) -> None:
        ops = CalendarOps()
        ops._com_available = True
        result = await ops.execute("check_freebusy", {
            "start_time": "2025-06-01 11:00",
            "end_time": "2025-06-01 10:00",
        })
        assert "error" in result


# ======================================================================
# 注册表检查
# ======================================================================


class TestRegistry:
    """验证 CalendarOps 在 TOOL_REGISTRY 中注册。"""

    def test_registered(self) -> None:
        from src.tools import TOOL_REGISTRY
        assert "calendar_ops" in TOOL_REGISTRY
        assert TOOL_REGISTRY["calendar_ops"] is CalendarOps
