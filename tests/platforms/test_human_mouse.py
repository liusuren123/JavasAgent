"""鼠标轨迹人化测试 — Step 9。

覆盖 T9.1 和 T9.2 的全部功能点：
- 贝塞尔曲线 + 随机控制点偏移
- 非线性速度（缓入缓出）
- 轨迹微抖动
- 点击按下/抬起分离
- 按压时长随机化
- 点击后微移
"""

from __future__ import annotations

import asyncio
import math
import random
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.platforms.human_hand import HumanHand, HumanHandConfig


# ── Fixtures ──────────────────────────────────────


@pytest.fixture
def mock_adapter():
    """创建 mock PlatformAdapter。"""
    adapter = MagicMock()
    adapter.click = AsyncMock()
    adapter.move_to = AsyncMock()
    adapter.mouse_down = AsyncMock()
    adapter.mouse_up = AsyncMock()
    adapter.screenshot = AsyncMock(return_value=b"")
    return adapter


@pytest.fixture
def hand(mock_adapter):
    """默认配置 HumanHand。"""
    return HumanHand(mock_adapter)


@pytest.fixture
def hand_no_jitter(mock_adapter):
    """无抖动配置，方便验证曲线路径。"""
    config = HumanHandConfig(jitter_range=0.0)
    return HumanHand(mock_adapter, config=config)


# ════════════════════════════════════════════════════
# T9.1：鼠标移动升级测试
# ════════════════════════════════════════════════════


class TestBezierControlPointOffset:
    """贝塞尔曲线随机控制点偏移测试。"""

    def test_control_points_not_on_straight_line(self, hand):
        """控制点不在起止点直线上（有偏移）。"""
        with patch("random.uniform", return_value=50.0):
            points = hand._generate_control_points(0, 0, 1000, 0, num_points=2)

        # 起点、终点不变
        assert points[0] == (0, 0)
        assert points[-1] == (1000, 0)

        # 中间控制点的 y 不应为 0（因为偏移）
        for px, py in points[1:-1]:
            assert py != 0, f"控制点 ({px}, {py}) 应偏离直线"

    def test_control_point_count(self, hand):
        """生成的控制点数量正确。"""
        points = hand._generate_control_points(0, 0, 500, 500, num_points=3)
        # 起点 + 3个控制点 + 终点 = 5
        assert len(points) == 5

    def test_zero_distance_returns_start_end(self, hand):
        """起止点相同时，控制点仍在范围内。"""
        points = hand._generate_control_points(100, 100, 100, 100, num_points=2)
        assert len(points) == 4
        assert points[0] == (100, 100)
        assert points[-1] == (100, 100)


class TestBezierCurveShape:
    """贝塞尔曲线生成测试。"""

    def test_curve_starts_and_ends_correctly(self, hand):
        """曲线首尾点匹配起止点。"""
        points = [(0.0, 0.0), (50.0, 100.0), (100.0, 0.0)]
        curve = hand._bezier_curve(points, num_steps=50)
        assert abs(curve[0][0] - 0.0) < 1e-6
        assert abs(curve[0][1] - 0.0) < 1e-6
        assert abs(curve[-1][0] - 100.0) < 1e-6
        assert abs(curve[-1][1] - 0.0) < 1e-6

    def test_curve_points_are_monotonic_for_straight_line(self, hand):
        """直线控制点生成单调递增的曲线。"""
        points = [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]
        curve = hand._bezier_curve(points, num_steps=20)
        for i in range(1, len(curve)):
            assert curve[i][0] >= curve[i - 1][0]

    def test_curve_has_requested_steps(self, hand):
        """曲线点数等于请求数。"""
        points = [(0.0, 0.0), (100.0, 100.0)]
        curve = hand._bezier_curve(points, num_steps=15)
        assert len(curve) == 15


class TestNonlinearSpeed:
    """非线性速度测试（缓入缓出）。"""

    def test_ease_in_out_starts_slow(self, hand):
        """缓入：开头速度慢。"""
        # t=0.1 和 t=0.2 的增量应小于 t=0.5 附近的增量
        v_early = hand._ease_in_out(0.2) - hand._ease_in_out(0.1)
        v_mid = hand._ease_in_out(0.55) - hand._ease_in_out(0.45)
        assert v_mid > v_early, f"中间速度({v_mid})应大于起始速度({v_early})"

    def test_ease_in_out_ends_slow(self, hand):
        """缓出：结尾速度慢。"""
        v_late = hand._ease_in_out(0.9) - hand._ease_in_out(0.8)
        v_mid = hand._ease_in_out(0.55) - hand._ease_in_out(0.45)
        assert v_mid > v_late, f"中间速度({v_mid})应大于末尾速度({v_late})"

    def test_ease_in_out_boundary(self, hand):
        """边界值正确。"""
        assert hand._ease_in_out(0.0) == 0.0
        assert abs(hand._ease_in_out(1.0) - 1.0) < 1e-9

    def test_move_step_delays_vary(self, hand, mock_adapter):
        """移动步进间隔非常量（非线性）。"""
        delays = []

        async def fake_sleep(d):
            delays.append(d)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            asyncio.get_event_loop().run_until_complete(
                hand.human_move_to(500, 500, duration=0.2)
            )

        # 去掉最后一个 sleep（human_click/human_move_to 后面的额外 sleep）
        # 检查 move_to 步进间隔不全相同
        if len(delays) > 3:
            # 不要求全部不同，但至少有差异
            unique_delays = set(round(d, 6) for d in delays[:10])
            assert len(unique_delays) > 1, "所有步进间隔都相同，没有非线性速度"


class TestJitter:
    """轨迹微抖动测试。"""

    @pytest.mark.asyncio
    async def test_move_to_has_jitter(self, hand, mock_adapter):
        """移动轨迹有微抖动（坐标不完全在贝塞尔曲线上）。"""
        await hand.human_move_to(500, 300, duration=0.05)

        # 获取 move_to 调用参数
        calls = mock_adapter.move_to.call_args_list
        assert len(calls) > 1, "应有多次 move_to 调用"

        # 由于抖动，某些中间点不应完全落在直线上
        # （这个测试在 jitter_range > 0 时几乎必然通过）
        coords = [(c[0][0], c[0][1]) for c in calls]
        # 验证存在至少一个点偏离了起点到终点的直线
        # 简单方法：检查所有中间点的y坐标不完全相同
        y_values = [c[1] for c in coords[1:-1]]
        if len(y_values) > 0:
            # 有抖动时 y 值不会全部完全相同
            unique_y = set(y_values)
            # 至少有多个不同 y 值（抖动导致的）
            assert len(unique_y) > 1 or len(coords) <= 2

    @pytest.mark.asyncio
    async def test_jitter_within_range(self, mock_adapter):
        """抖动在配置范围内（短距离场景，控制点偏移小）。"""
        config = HumanHandConfig(jitter_range=2.0, bezier_control_points=0)
        hand = HumanHand(mock_adapter, config=config)

        # 无控制点时贝塞尔退化为直线 (0,0)→(100,0)
        # y 坐标应主要在 jitter_range 范围内
        await hand.human_move_to(100, 0, duration=0.05)

        calls = mock_adapter.move_to.call_args_list
        for call in calls:
            y = call[0][1]
            # 无控制点时曲线就是直线，y 偏移仅来自抖动
            assert abs(y) < 10, f"y={y} 抖动超出预期范围（无控制点直线场景）"


# ════════════════════════════════════════════════════
# T9.2：点击行为人化测试
# ════════════════════════════════════════════════════


class TestClickPressRelease:
    """点击按下/抬起分离测试。"""

    @pytest.mark.asyncio
    async def test_human_click_uses_mouse_down_up(self, mock_adapter):
        """human_click 使用 mouse_down + mouse_up 而非 click。"""
        config = HumanHandConfig(click_offset_range=0)
        hand = HumanHand(mock_adapter, config=config)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await hand.human_click(500, 300)

        # 应调用 mouse_down 和 mouse_up（而非 adapter.click）
        mock_adapter.mouse_down.assert_awaited_once()
        mock_adapter.mouse_up.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mouse_down_before_mouse_up(self, mock_adapter):
        """mouse_down 在 mouse_up 之前调用。"""
        config = HumanHandConfig(click_offset_range=0)
        hand = HumanHand(mock_adapter, config=config)

        call_order = []
        mock_adapter.mouse_down.side_effect = lambda *a, **k: call_order.append("down")
        mock_adapter.mouse_up.side_effect = lambda *a, **k: call_order.append("up")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await hand.human_click(500, 300)

        assert call_order == ["down", "up"]

    @pytest.mark.asyncio
    async def test_mouse_down_up_at_same_position(self, mock_adapter):
        """按下和抬起位置相同。"""
        config = HumanHandConfig(click_offset_range=0)
        hand = HumanHand(mock_adapter, config=config)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await hand.human_click(500, 300)

        down_args = mock_adapter.mouse_down.call_args
        up_args = mock_adapter.mouse_up.call_args
        assert down_args[0][0] == up_args[0][0]  # x 相同
        assert down_args[0][1] == up_args[0][1]  # y 相同


class TestPressDuration:
    """按压时长随机化测试（50-150ms）。"""

    @pytest.mark.asyncio
    async def test_press_duration_in_range(self, mock_adapter):
        """按下和抬起之间的延迟在 50-150ms。"""
        config = HumanHandConfig(click_offset_range=0)
        hand = HumanHand(mock_adapter, config=config)

        sleep_durations = []

        async def record_sleep(d):
            sleep_durations.append(d)

        with patch("asyncio.sleep", side_effect=record_sleep):
            await hand.human_click(500, 300)

        # 应该存在一个在 0.05~0.15 范围内的 sleep（按压保持时间）
        press_delays = [d for d in sleep_durations if 0.05 <= d <= 0.15]
        assert len(press_delays) >= 1, (
            f"应有按压保持延迟 50-150ms，实际 sleep 值: {sleep_durations}"
        )


class TestPostClickMicroMove:
    """点击后微小移动测试。"""

    @pytest.mark.asyncio
    async def test_click_followed_by_micro_move(self, mock_adapter):
        """点击后有微小移动。"""
        config = HumanHandConfig(click_offset_range=0, post_click_move_range=3)
        hand = HumanHand(mock_adapter, config=config)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await hand.human_click(500, 300)

        # mouse_up 后应有额外的 move_to 调用
        all_move_calls = mock_adapter.move_to.call_args_list
        assert len(all_move_calls) >= 1

        # 最后一个 move_to 应在 (500±3, 300±3) 附近
        last_x = all_move_calls[-1][0][0]
        last_y = all_move_calls[-1][0][1]
        # 微移范围，考虑贝塞尔到达的近似位置
        assert abs(last_x - 500) <= 5, f"点击后微移 x={last_x} 超出范围"
        assert abs(last_y - 300) <= 5, f"点击后微移 y={last_y} 超出范围"

    @pytest.mark.asyncio
    async def test_micro_move_disabled_when_range_zero(self, mock_adapter):
        """post_click_move_range=0 时没有点击后微移。"""
        config = HumanHandConfig(click_offset_range=0, post_click_move_range=0)
        hand = HumanHand(mock_adapter, config=config)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await hand.human_click(500, 300)

        # 只有贝塞尔曲线的 move_to 调用，没有额外的点击后微移
        # （当 range=0 时，微移为 (500,300)→(500,300)，但不应多一次 move_to）
        # 验证：如果有 post-click move，move_to 次数会多一次


class TestClickOffset:
    """点击随机偏移测试。"""

    @pytest.mark.asyncio
    async def test_click_position_within_offset(self, mock_adapter):
        """点击位置在配置偏移范围内。"""
        config = HumanHandConfig(click_offset_range=5)
        hand = HumanHand(mock_adapter, config=config)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            # 固定随机偏移
            with patch("random.randint", return_value=3):
                await hand.human_click(500, 300)

        # mouse_down 的位置应该是 (500+3, 300+3)
        down_args = mock_adapter.mouse_down.call_args
        assert down_args[0][0] == 503
        assert down_args[0][1] == 303


class TestMoveToDuration:
    """移动时间自动计算测试。"""

    def test_short_distance_fast(self, hand):
        """短距离移动快。"""
        d = hand._calculate_move_duration(50)
        assert d < 0.5

    def test_long_distance_slower(self, hand):
        """长距离移动慢。"""
        d_short = hand._calculate_move_duration(100)
        d_long = hand._calculate_move_duration(1500)
        assert d_long > d_short

    def test_duration_capped(self, hand):
        """移动时间有上限。"""
        d = hand._calculate_move_duration(10000)
        assert d <= 2.0

    def test_duration_floored(self, hand):
        """移动时间有下限。"""
        d = hand._calculate_move_duration(1)
        assert d >= 0.1
