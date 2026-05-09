"""通知管理器测试。"""

from __future__ import annotations

import asyncio

import pytest

from src.core.notification import (
    Notification,
    NotificationLevel,
    NotificationManager,
    NotificationRule,
)


class TestNotify:
    """测试 notify() 创建通知。"""

    async def test_notify_returns_notification(self) -> None:
        mgr = NotificationManager()
        n = await mgr.notify("标题", "内容")
        assert isinstance(n, Notification)
        assert n.title == "标题"
        assert n.message == "内容"
        assert n.level == NotificationLevel.INFO
        assert n.is_read is False
        assert n.id != ""

    async def test_notify_with_all_params(self) -> None:
        mgr = NotificationManager()
        n = await mgr.notify(
            title="警告",
            message="磁盘空间不足",
            level=NotificationLevel.WARNING,
            source="monitor",
            metadata={"disk": "/dev/sda1", "usage": 95},
        )
        assert n.level == NotificationLevel.WARNING
        assert n.source == "monitor"
        assert n.metadata["disk"] == "/dev/sda1"

    async def test_notify_default_level_is_info(self) -> None:
        mgr = NotificationManager()
        n = await mgr.notify("测试", "消息")
        assert n.level == NotificationLevel.INFO

    async def test_notify_default_source_empty(self) -> None:
        mgr = NotificationManager()
        n = await mgr.notify("测试", "消息")
        assert n.source == ""

    async def test_notify_default_metadata_empty_dict(self) -> None:
        mgr = NotificationManager()
        n = await mgr.notify("测试", "消息")
        assert n.metadata == {}

    async def test_notify_unique_ids(self) -> None:
        mgr = NotificationManager()
        n1 = await mgr.notify("a", "1")
        n2 = await mgr.notify("b", "2")
        assert n1.id != n2.id


class TestGetUnreadAndMarkRead:
    """测试 get_unread() 和 mark_read()。"""

    async def test_get_unread_returns_unread(self) -> None:
        mgr = NotificationManager()
        await mgr.notify("a", "1")
        await mgr.notify("b", "2")
        unread = await mgr.get_unread()
        assert len(unread) == 2
        assert all(not n.is_read for n in unread)

    async def test_get_unread_respects_limit(self) -> None:
        mgr = NotificationManager()
        for i in range(10):
            await mgr.notify(f"标题{i}", f"内容{i}")
        unread = await mgr.get_unread(limit=3)
        assert len(unread) == 3

    async def test_get_unread_newest_first(self) -> None:
        mgr = NotificationManager()
        await mgr.notify("旧", "旧消息")
        await mgr.notify("新", "新消息")
        unread = await mgr.get_unread()
        assert unread[0].title == "新"

    async def test_mark_read_removes_from_unread(self) -> None:
        mgr = NotificationManager()
        n = await mgr.notify("测试", "内容")
        assert len(await mgr.get_unread()) == 1

        result = await mgr.mark_read(n.id)
        assert result is True
        assert len(await mgr.get_unread()) == 0

    async def test_mark_read_nonexistent_returns_false(self) -> None:
        mgr = NotificationManager()
        result = await mgr.mark_read("不存在的id")
        assert result is False

    async def test_mark_read_idempotent(self) -> None:
        mgr = NotificationManager()
        n = await mgr.notify("测试", "内容")
        assert await mgr.mark_read(n.id) is True
        assert await mgr.mark_read(n.id) is True  # 重复标记仍然返回 True

    async def test_get_unread_empty_when_all_read(self) -> None:
        mgr = NotificationManager()
        n1 = await mgr.notify("a", "1")
        n2 = await mgr.notify("b", "2")
        await mgr.mark_read(n1.id)
        await mgr.mark_read(n2.id)
        assert await mgr.get_unread() == []


class TestGetHistory:
    """测试 get_history() 按级别过滤。"""

    async def test_get_history_returns_all(self) -> None:
        mgr = NotificationManager()
        await mgr.notify("info", "1", level=NotificationLevel.INFO)
        await mgr.notify("warn", "2", level=NotificationLevel.WARNING)
        await mgr.notify("urgent", "3", level=NotificationLevel.URGENT)
        history = await mgr.get_history()
        assert len(history) == 3

    async def test_get_history_filter_by_level(self) -> None:
        mgr = NotificationManager()
        await mgr.notify("info", "1", level=NotificationLevel.INFO)
        await mgr.notify("warn", "2", level=NotificationLevel.WARNING)
        await mgr.notify("urgent", "3", level=NotificationLevel.URGENT)

        warnings = await mgr.get_history(level=NotificationLevel.WARNING)
        assert len(warnings) == 1
        assert warnings[0].level == NotificationLevel.WARNING

    async def test_get_history_respects_limit(self) -> None:
        mgr = NotificationManager()
        for i in range(20):
            await mgr.notify(f"标题{i}", f"内容{i}")
        history = await mgr.get_history(limit=5)
        assert len(history) == 5

    async def test_get_history_newest_first(self) -> None:
        mgr = NotificationManager()
        await mgr.notify("旧", "旧消息")
        await mgr.notify("新", "新消息")
        history = await mgr.get_history()
        assert history[0].title == "新"

    async def test_get_history_empty(self) -> None:
        mgr = NotificationManager()
        history = await mgr.get_history()
        assert history == []

    async def test_get_history_filter_no_match(self) -> None:
        mgr = NotificationManager()
        await mgr.notify("info", "1", level=NotificationLevel.INFO)
        history = await mgr.get_history(level=NotificationLevel.URGENT)
        assert history == []


class TestRegisterHandlerAndDispatch:
    """测试 register_handler() 和 dispatch() 的分发逻辑。"""

    async def test_handler_called_on_dispatch(self) -> None:
        mgr = NotificationManager()
        received: list[Notification] = []
        mgr.register_handler(NotificationLevel.INFO, lambda n: received.append(n))

        n = Notification(
            id="test-1",
            title="测试",
            message="内容",
            level=NotificationLevel.INFO,
        )
        await mgr.dispatch(n)
        assert len(received) == 1
        assert received[0].id == "test-1"

    async def test_handler_only_for_registered_level(self) -> None:
        mgr = NotificationManager()
        info_received: list[Notification] = []
        urgent_received: list[Notification] = []

        mgr.register_handler(NotificationLevel.INFO, lambda n: info_received.append(n))
        mgr.register_handler(NotificationLevel.URGENT, lambda n: urgent_received.append(n))

        n = Notification(
            id="test-1",
            title="测试",
            message="内容",
            level=NotificationLevel.INFO,
        )
        await mgr.dispatch(n)
        assert len(info_received) == 1
        assert len(urgent_received) == 0

    async def test_multiple_handlers_same_level(self) -> None:
        mgr = NotificationManager()
        log: list[str] = []
        mgr.register_handler(NotificationLevel.WARNING, lambda n: log.append("handler1"))
        mgr.register_handler(NotificationLevel.WARNING, lambda n: log.append("handler2"))

        n = Notification(
            id="test-1",
            title="警告",
            message="内容",
            level=NotificationLevel.WARNING,
        )
        await mgr.dispatch(n)
        assert log == ["handler1", "handler2"]

    async def test_async_handler(self) -> None:
        mgr = NotificationManager()
        received: list[Notification] = []

        async def async_handler(n: Notification) -> None:
            received.append(n)

        mgr.register_handler(NotificationLevel.INFO, async_handler)

        n = Notification(
            id="test-async",
            title="异步测试",
            message="内容",
            level=NotificationLevel.INFO,
        )
        await mgr.dispatch(n)
        assert len(received) == 1

    async def test_handler_exception_does_not_crash(self) -> None:
        mgr = NotificationManager()
        received: list[Notification] = []

        def bad_handler(n: Notification) -> None:
            raise RuntimeError("处理器出错")

        def good_handler(n: Notification) -> None:
            received.append(n)

        mgr.register_handler(NotificationLevel.INFO, bad_handler)
        mgr.register_handler(NotificationLevel.INFO, good_handler)

        n = Notification(
            id="test-err",
            title="错误测试",
            message="内容",
            level=NotificationLevel.INFO,
        )
        # 不应抛出异常
        await mgr.dispatch(n)
        # good_handler 仍应被调用
        assert len(received) == 1

    async def test_notify_triggers_dispatch(self) -> None:
        mgr = NotificationManager()
        received: list[Notification] = []
        mgr.register_handler(NotificationLevel.INFO, lambda n: received.append(n))

        await mgr.notify("测试", "通过 notify 触发分发")
        assert len(received) == 1
        assert received[0].title == "测试"


class TestAddRule:
    """测试 add_rule() 和 notify 时的规则自动升级。"""

    async def test_rule_upgrades_level(self) -> None:
        mgr = NotificationManager()
        # 规则：source 为 "monitor" 的通知自动升级为 URGENT
        mgr.add_rule(NotificationRule(
            rule_id="monitor-urgent",
            event_type="monitor_failure",
            condition="monitor",
            level=NotificationLevel.URGENT,
        ))
        n = await mgr.notify(
            "磁盘告警", "磁盘空间不足", level=NotificationLevel.WARNING, source="monitor"
        )
        assert n.level == NotificationLevel.URGENT

    async def test_rule_with_callable_condition(self) -> None:
        mgr = NotificationManager()
        # 规则：metadata 中 fail_count >= 3 时升级为 URGENT
        mgr.add_rule(NotificationRule(
            rule_id="retry-failure",
            event_type="retry_exhausted",
            condition=lambda title, source, metadata: metadata.get("fail_count", 0) >= 3,
            level=NotificationLevel.URGENT,
        ))
        n = await mgr.notify(
            "执行失败", "重试耗尽", level=NotificationLevel.WARNING, metadata={"fail_count": 3}
        )
        assert n.level == NotificationLevel.URGENT

    async def test_rule_not_matching_keeps_original_level(self) -> None:
        mgr = NotificationManager()
        mgr.add_rule(NotificationRule(
            rule_id="monitor-urgent",
            event_type="monitor_failure",
            condition="monitor",
            level=NotificationLevel.URGENT,
        ))
        n = await mgr.notify("普通", "不匹配规则", level=NotificationLevel.INFO, source="other")
        assert n.level == NotificationLevel.INFO

    async def test_disabled_rule_not_applied(self) -> None:
        mgr = NotificationManager()
        mgr.add_rule(NotificationRule(
            rule_id="disabled-rule",
            event_type="test",
            condition="monitor",
            level=NotificationLevel.URGENT,
            enabled=False,
        ))
        n = await mgr.notify("测试", "禁用规则", level=NotificationLevel.INFO, source="monitor")
        assert n.level == NotificationLevel.INFO

    async def test_no_rules_keeps_level(self) -> None:
        mgr = NotificationManager()
        n = await mgr.notify("测试", "无规则", level=NotificationLevel.WARNING)
        assert n.level == NotificationLevel.WARNING


class TestGetStats:
    """测试 get_stats() 返回正确统计。"""

    async def test_empty_stats(self) -> None:
        mgr = NotificationManager()
        stats = mgr.get_stats()
        assert stats["total"] == 0
        assert stats["unread"] == 0
        assert stats["by_level"]["info"] == 0
        assert stats["by_level"]["warning"] == 0
        assert stats["by_level"]["urgent"] == 0

    async def test_stats_after_notifications(self) -> None:
        mgr = NotificationManager()
        await mgr.notify("info1", "1", level=NotificationLevel.INFO)
        await mgr.notify("info2", "2", level=NotificationLevel.INFO)
        await mgr.notify("warn1", "3", level=NotificationLevel.WARNING)
        await mgr.notify("urgent1", "4", level=NotificationLevel.URGENT)

        stats = mgr.get_stats()
        assert stats["total"] == 4
        assert stats["unread"] == 4
        assert stats["by_level"]["info"] == 2
        assert stats["by_level"]["warning"] == 1
        assert stats["by_level"]["urgent"] == 1

    async def test_stats_after_mark_read(self) -> None:
        mgr = NotificationManager()
        n1 = await mgr.notify("read", "1", level=NotificationLevel.INFO)
        await mgr.notify("unread", "2", level=NotificationLevel.WARNING)
        await mgr.mark_read(n1.id)

        stats = mgr.get_stats()
        assert stats["total"] == 2
        assert stats["unread"] == 1


class TestConcurrency:
    """测试并发安全。"""

    async def test_concurrent_notify(self) -> None:
        mgr = NotificationManager()

        async def send_batch(prefix: str, count: int) -> None:
            for i in range(count):
                await mgr.notify(f"{prefix}-{i}", f"内容{i}")

        # 10 个协程并发发送，每个 20 条
        tasks = [send_batch(f"worker{i}", 20) for i in range(10)]
        await asyncio.gather(*tasks)

        stats = mgr.get_stats()
        assert stats["total"] == 200

    async def test_concurrent_notify_and_read(self) -> None:
        mgr = NotificationManager()

        async def send_notifications() -> list[Notification]:
            results = []
            for i in range(10):
                n = await mgr.notify(f"标题{i}", f"内容{i}")
                results.append(n)
            return results

        async def read_notifications() -> None:
            for _ in range(5):
                await mgr.get_unread()

        send_task = asyncio.create_task(send_notifications())
        read_task = asyncio.create_task(read_notifications())
        notifications, _ = await asyncio.gather(send_task, read_task)

        # 随机标记几个已读
        for n in notifications[:3]:
            await mgr.mark_read(n.id)

        stats = mgr.get_stats()
        assert stats["total"] == 10
        assert stats["unread"] == 7
