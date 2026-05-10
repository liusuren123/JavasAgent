"""MotorController 闭环控制器测试。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.platforms.motor_controller import (
    ActionStatus,
    ActionResult,
    MotorController,
    MotorControllerConfig,
)
from src.perception.target_cache import TargetInfo
from src.perception.target_matcher import MatchLevel, MatchResult


# ── 测试辅助 ──────────────────────────────────────


def _make_target(
    text: str = "保存按钮",
    cx: int = 500,
    cy: int = 300,
    element_type: str = "button",
) -> TargetInfo:
    """构造一个 TargetInfo 用于测试。"""
    return TargetInfo(
        target_id="test-id",
        text=text,
        bbox=(cx - 50, cy - 20, 100, 40),
        center=(cx, cy),
        element_type=element_type,
        confidence=0.9,
        screen_region="center",
        created_at=0.0,
    )


def _make_match_result(
    target: TargetInfo | None = None,
    level: MatchLevel = MatchLevel.EXACT,
    score: float = 1.0,
) -> MatchResult | None:
    """构造一个 MatchResult 或返回 None。"""
    if target is None:
        return None
    return MatchResult(
        target=target,
        level=level,
        score=score,
        confidence=score,
    )


def _make_controller(
    config: MotorControllerConfig | None = None,
) -> tuple[MotorController, AsyncMock, AsyncMock, AsyncMock]:
    """构造 MotorController + mock eye/hand/adapter。"""
    eye = AsyncMock()
    hand = AsyncMock()
    adapter = AsyncMock()
    adapter.screenshot = AsyncMock(return_value=b"fake-screenshot")
    eye.capture_and_analyze = AsyncMock(return_value=MagicMock())

    ctrl = MotorController(eye, hand, adapter, config)
    return ctrl, eye, hand, adapter


# ── 1-5: 数据类与枚举测试 ──────────────────────────


class TestConfigAndDataClasses:
    """配置类和枚举测试。"""

    def test_config_defaults(self):
        """MotorControllerConfig 默认值正确。"""
        cfg = MotorControllerConfig()
        assert cfg.max_attempts == 3
        assert cfg.verify_delay == 0.5
        assert cfg.action_timeout == 10.0
        assert cfg.screenshot_interval == 0.3
        assert cfg.click_tolerance == 10

    def test_config_custom(self):
        """自定义配置生效。"""
        cfg = MotorControllerConfig(
            max_attempts=5,
            verify_delay=1.0,
            action_timeout=30.0,
            screenshot_interval=0.1,
            click_tolerance=20,
        )
        assert cfg.max_attempts == 5
        assert cfg.verify_delay == 1.0
        assert cfg.action_timeout == 30.0
        assert cfg.screenshot_interval == 0.1
        assert cfg.click_tolerance == 20

    def test_init_default_config(self):
        """不传 config 时使用默认配置。"""
        ctrl, _, _, _ = _make_controller()
        assert isinstance(ctrl._config, MotorControllerConfig)
        assert ctrl._config.max_attempts == 3

    def test_action_result_fields(self):
        """ActionResult 各字段可正确赋值。"""
        result = ActionResult(
            status=ActionStatus.SUCCESS,
            message="ok",
            attempts=2,
            duration_ms=123.4,
            target_coords=(100, 200),
        )
        assert result.status == ActionStatus.SUCCESS
        assert result.message == "ok"
        assert result.attempts == 2
        assert result.duration_ms == 123.4
        assert result.target_coords == (100, 200)

    def test_action_status_enum(self):
        """ActionStatus 枚举值完整（5个状态）。"""
        expected = {
            "SUCCESS",
            "TARGET_NOT_FOUND",
            "ACTION_FAILED",
            "VERIFICATION_FAILED",
            "TIMEOUT",
        }
        actual = {s.name for s in ActionStatus}
        assert actual == expected


# ── 6-9: click_target 测试 ──────────────────────────


class TestClickTarget:
    """click_target 闭环点击测试。"""

    @pytest.mark.asyncio
    async def test_click_target_success(self):
        """闭环点击成功：eye 找到目标 → hand 点击 → 验证目标消失 → SUCCESS。"""
        ctrl, eye, hand, _ = _make_controller()

        target = _make_target()
        match = _make_match_result(target)

        # 第1次 find_target 找到，第2次（验证）目标消失
        eye.find_target = AsyncMock(side_effect=[match, None])

        result = await ctrl.click_target("保存按钮")

        assert result.status == ActionStatus.SUCCESS
        assert result.target_coords == (500, 300)
        assert result.attempts == 1
        hand.human_click.assert_awaited_once_with(500, 300)

    @pytest.mark.asyncio
    async def test_click_target_not_found(self):
        """目标未找到 → TARGET_NOT_FOUND。"""
        cfg = MotorControllerConfig(max_attempts=2)
        ctrl, eye, hand, _ = _make_controller(cfg)

        eye.find_target = AsyncMock(return_value=None)

        result = await ctrl.click_target("不存在的按钮")

        assert result.status == ActionStatus.TARGET_NOT_FOUND
        assert result.attempts == 2
        hand.human_click.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_click_target_retry_success(self):
        """第1次失败第2次成功 → attempts=2, SUCCESS。"""
        cfg = MotorControllerConfig(max_attempts=3)
        ctrl, eye, hand, _ = _make_controller(cfg)

        target = _make_target()
        match = _make_match_result(target)

        # 第1次循环: find_target 找到 → 点击成功 → 验证目标还在(失败)
        # 第2次循环: find_target 找到 → 点击成功 → 验证目标消失(成功)
        eye.find_target = AsyncMock(side_effect=[match, match, match, None])

        result = await ctrl.click_target("保存按钮", verify_change=True)

        assert result.status == ActionStatus.SUCCESS
        assert result.attempts == 2

    @pytest.mark.asyncio
    async def test_click_target_max_retry(self):
        """超过最大重试 → TIMEOUT。"""
        cfg = MotorControllerConfig(max_attempts=2, verify_delay=0)
        ctrl, eye, hand, _ = _make_controller(cfg)

        # find_target 始终返回 None
        eye.find_target = AsyncMock(return_value=None)

        result = await ctrl.click_target("不存在的按钮")

        assert result.status == ActionStatus.TARGET_NOT_FOUND
        assert result.attempts == 2


# ── 10-12: type_in_field 测试 ──────────────────────


class TestTypeInField:
    """type_in_field 闭环输入测试。"""

    @pytest.mark.asyncio
    async def test_type_in_field_success(self):
        """找到输入框 → 点击聚焦 → 输入文本 → SUCCESS。"""
        ctrl, eye, hand, _ = _make_controller(
            MotorControllerConfig(verify_delay=0)
        )

        target = _make_target("用户名输入框", 200, 150, "input")
        match = _make_match_result(target)
        eye.find_target = AsyncMock(return_value=match)

        result = await ctrl.type_in_field("用户名输入框", "hello")

        assert result.status == ActionStatus.SUCCESS
        assert result.target_coords == (200, 150)
        hand.human_click.assert_awaited_once_with(200, 150)
        hand.human_type.assert_awaited_once_with("hello")

    @pytest.mark.asyncio
    async def test_type_in_field_not_found(self):
        """输入框未找到 → TARGET_NOT_FOUND。"""
        cfg = MotorControllerConfig(max_attempts=2)
        ctrl, eye, hand, _ = _make_controller(cfg)

        eye.find_target = AsyncMock(return_value=None)

        result = await ctrl.type_in_field("不存在的输入框", "text")

        assert result.status == ActionStatus.TARGET_NOT_FOUND
        assert result.attempts == 2
        hand.human_type.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_type_in_field_with_enter(self):
        """press_enter=True 时按回车。"""
        ctrl, eye, hand, _ = _make_controller(
            MotorControllerConfig(verify_delay=0)
        )

        target = _make_target("搜索框", 300, 100, "input")
        match = _make_match_result(target)
        eye.find_target = AsyncMock(return_value=match)

        result = await ctrl.type_in_field("搜索框", "query", press_enter=True)

        assert result.status == ActionStatus.SUCCESS
        hand.human_press_key.assert_awaited_once_with("enter")


# ── 13-14: wait_and_click 测试 ─────────────────────


class TestWaitAndClick:
    """wait_and_click 等待后点击测试。"""

    @pytest.mark.asyncio
    async def test_wait_and_click_success(self):
        """等待后目标出现并点击成功。"""
        ctrl, eye, hand, _ = _make_controller()

        target = _make_target()
        match = _make_match_result(target)
        eye.find_target = AsyncMock(return_value=match)

        result = await ctrl.wait_and_click("保存按钮", timeout=1.0, poll_interval=0.01)

        assert result.status == ActionStatus.SUCCESS
        assert result.target_coords == (500, 300)
        hand.human_click.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_wait_and_click_timeout(self):
        """超时未出现 → TIMEOUT。"""
        ctrl, eye, hand, _ = _make_controller()

        eye.find_target = AsyncMock(return_value=None)

        result = await ctrl.wait_and_click("永不出现", timeout=0.1, poll_interval=0.05)

        assert result.status == ActionStatus.TIMEOUT
        hand.human_click.assert_not_awaited()


# ── 15-16: wait_for_target 测试 ────────────────────


class TestWaitForTarget:
    """wait_for_target 等待目标出现测试。"""

    @pytest.mark.asyncio
    async def test_wait_for_target_success(self):
        """等待目标出现，不点击。"""
        ctrl, eye, hand, _ = _make_controller()

        target = _make_target()
        match = _make_match_result(target)
        eye.find_target = AsyncMock(return_value=match)

        result = await ctrl.wait_for_target("保存按钮", timeout=1.0, poll_interval=0.01)

        assert result.status == ActionStatus.SUCCESS
        assert result.target_coords == (500, 300)
        # 不应点击
        hand.human_click.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wait_for_target_timeout(self):
        """等待超时。"""
        ctrl, eye, hand, _ = _make_controller()

        eye.find_target = AsyncMock(return_value=None)

        result = await ctrl.wait_for_target("永不出现", timeout=0.1, poll_interval=0.05)

        assert result.status == ActionStatus.TIMEOUT
        hand.human_click.assert_not_awaited()


# ── 17-18: scroll_and_find 测试 ────────────────────


class TestScrollAndFind:
    """scroll_and_find 滚动查找测试。"""

    @pytest.mark.asyncio
    async def test_scroll_and_find_found(self):
        """滚动后找到目标。"""
        cfg = MotorControllerConfig(screenshot_interval=0)
        ctrl, eye, hand, _ = _make_controller(cfg)

        target = _make_target()
        match = _make_match_result(target)

        # 前 2 次找不到，第 3 次找到
        eye.find_target = AsyncMock(side_effect=[None, None, match])

        result = await ctrl.scroll_and_find("保存按钮", max_scrolls=3)

        assert result.status == ActionStatus.SUCCESS
        assert result.target_coords == (500, 300)
        # 应该滚动了 2 次（第 0 次不滚动，第 1 次滚动后仍没找到，第 2 次滚动后找到）
        assert hand.human_scroll.await_count == 2

    @pytest.mark.asyncio
    async def test_scroll_and_find_exhausted(self):
        """滚动次数用完未找到。"""
        cfg = MotorControllerConfig(screenshot_interval=0)
        ctrl, eye, hand, _ = _make_controller(cfg)

        eye.find_target = AsyncMock(return_value=None)

        result = await ctrl.scroll_and_find("永不出现", max_scrolls=3)

        assert result.status == ActionStatus.TARGET_NOT_FOUND
        # scroll 3 次 + 初始检查 1 次 = 4 次截图查找
        assert hand.human_scroll.await_count == 3


# ── 19: verify_target_gone 测试 ────────────────────


class TestVerifyTargetGone:
    """_verify_target_gone 验证测试。"""

    @pytest.mark.asyncio
    async def test_verify_target_gone(self):
        """验证目标消失返回 True/False。"""
        ctrl, eye, _, _ = _make_controller()

        target = _make_target()
        match = _make_match_result(target)

        # 测试目标消失
        eye.find_target = AsyncMock(return_value=None)
        result_true = await ctrl._verify_target_gone("保存按钮")
        assert result_true is True

        # 测试目标仍在
        eye.find_target = AsyncMock(return_value=match)
        result_false = await ctrl._verify_target_gone("保存按钮")
        assert result_false is False


# ── 20: retry_action_wrapper 测试 ───────────────────


class TestRetryActionWrapper:
    """_retry_action 重试包装器测试。"""

    @pytest.mark.asyncio
    async def test_retry_action_wrapper(self):
        """重试包装器正确计数 attempts。"""
        ctrl, _, _, _ = _make_controller()

        call_count = 0

        async def action_factory():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return ActionResult(
                    status=ActionStatus.TARGET_NOT_FOUND,
                    message="没找到",
                )
            return ActionResult(
                status=ActionStatus.SUCCESS,
                message="找到了",
            )

        result = await ctrl._retry_action(action_factory, max_attempts=5)

        assert result.status == ActionStatus.SUCCESS
        assert result.attempts == 3
        assert call_count == 3
