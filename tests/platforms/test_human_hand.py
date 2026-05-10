"""HumanHand 拟人手部模拟器测试。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.platforms.human_hand import HumanHand, HumanHandConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_adapter():
    """创建一个 mock PlatformAdapter。"""
    adapter = MagicMock()
    adapter.click = AsyncMock()
    adapter.type_text = AsyncMock()
    adapter.press_key = AsyncMock()
    adapter.hotkey = AsyncMock()
    adapter.move_to = AsyncMock()
    adapter.scroll = AsyncMock()
    adapter.drag_to = AsyncMock()
    adapter.screenshot = AsyncMock(return_value=b"")
    return adapter


@pytest.fixture
def hand(mock_adapter):
    """默认配置的 HumanHand 实例。"""
    return HumanHand(mock_adapter)


@pytest.fixture
def hand_custom(mock_adapter):
    """自定义配置的 HumanHand 实例。"""
    config = HumanHandConfig(
        move_speed=2.0,
        click_offset_range=5,
        typo_probability=0.1,
        base_type_interval=0.1,
        bezier_control_points=2,
        jitter_range=1.0,
    )
    return HumanHand(mock_adapter, config=config)


# ---------------------------------------------------------------------------
# 1. 初始化测试
# ---------------------------------------------------------------------------

class TestInit:
    def test_init_default_config(self, mock_adapter):
        hand = HumanHand(mock_adapter)
        assert hand._config.move_speed == 1.0
        assert hand._config.click_offset_range == 3
        assert hand._config.typo_probability == 0.02
        assert hand._config.base_type_interval == 0.05
        assert hand._config.bezier_control_points == 3
        assert hand._config.jitter_range == 2.0

    def test_init_custom_config(self, mock_adapter):
        config = HumanHandConfig(
            move_speed=2.0,
            click_offset_range=5,
            typo_probability=0.1,
            base_type_interval=0.1,
            bezier_control_points=2,
            jitter_range=1.0,
        )
        hand = HumanHand(mock_adapter, config=config)
        assert hand._config.move_speed == 2.0
        assert hand._config.click_offset_range == 5
        assert hand._config.typo_probability == 0.1
        assert hand._config.base_type_interval == 0.1
        assert hand._config.bezier_control_points == 2
        assert hand._config.jitter_range == 1.0


# ---------------------------------------------------------------------------
# 2. 辅助方法测试
# ---------------------------------------------------------------------------

class TestBezierCurve:
    def test_bezier_curve_returns_correct_steps(self, hand):
        points = [(0.0, 0.0), (50.0, 50.0), (100.0, 100.0)]
        result = hand._bezier_curve(points, num_steps=20)
        assert len(result) == 20
        # 首尾点应接近起止点
        assert abs(result[0][0] - 0.0) < 1e-6
        assert abs(result[0][1] - 0.0) < 1e-6
        assert abs(result[-1][0] - 100.0) < 1e-6
        assert abs(result[-1][1] - 100.0) < 1e-6

    def test_bezier_curve_two_points(self, hand):
        """两点贝塞尔退化为直线。"""
        points = [(0.0, 0.0), (100.0, 0.0)]
        result = hand._bezier_curve(points, num_steps=11)
        assert len(result) == 11
        # 所有 y 坐标应为 0（直线）
        for _, y in result:
            assert abs(y) < 1e-6
        # 首尾 x 坐标
        assert abs(result[0][0]) < 1e-6
        assert abs(result[-1][0] - 100.0) < 1e-6


class TestEaseInOut:
    def test_ease_in_out_bounds(self, hand):
        # 边界值
        assert hand._ease_in_out(0.0) == 0.0
        assert abs(hand._ease_in_out(1.0) - 1.0) < 1e-9
        # 中间值在 [0, 1] 范围
        for t in [0.1, 0.25, 0.5, 0.75, 0.9]:
            v = hand._ease_in_out(t)
            assert 0.0 <= v <= 1.0, f"t={t} => v={v}"


class TestDistance:
    def test_distance_calculation(self, hand):
        assert hand._distance(0, 0, 3, 4) == pytest.approx(5.0)
        assert hand._distance(0, 0, 0, 0) == pytest.approx(0.0)
        assert hand._distance(1, 1, 4, 5) == pytest.approx(5.0)


class TestMoveDuration:
    def test_calculate_move_duration_short(self, hand):
        d = hand._calculate_move_duration(100)
        assert 0.1 < d < 0.5

    def test_calculate_move_duration_long(self, hand):
        d = hand._calculate_move_duration(2000)
        assert d <= 2.0
        assert d > 0.5


class TestRandomOffset:
    def test_random_offset_within_range(self, hand):
        for _ in range(100):
            v = hand._random_offset(1.0, ratio=0.5)
            assert 0.5 <= v <= 1.5, f"v={v}"


# ---------------------------------------------------------------------------
# 3. 鼠标操作测试
# ---------------------------------------------------------------------------

class TestHumanMoveTo:
    @pytest.mark.asyncio
    async def test_human_move_to_calls_adapter(self, hand, mock_adapter):
        await hand.human_move_to(100, 200, duration=0.05)
        # adapter.move_to 应被调用（多次，沿曲线路径）
        assert mock_adapter.move_to.call_count > 1


class TestHumanClick:
    @pytest.mark.asyncio
    async def test_human_click_sequence(self, hand, mock_adapter):
        """human_click 先移动再停顿再点击。"""
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await hand.human_click(100, 200)

        # move_to 应被调用（贝塞尔曲线路径）
        assert mock_adapter.move_to.call_count > 0
        # click 应被调用一次
        assert mock_adapter.click.call_count == 1
        # click 的坐标应在 (100±3, 200±3) 范围内
        call_args = mock_adapter.click.call_args
        cx, cy = call_args[0][0], call_args[0][1]
        assert 97 <= cx <= 103
        assert 197 <= cy <= 203


class TestHumanDrag:
    @pytest.mark.asyncio
    async def test_human_drag_uses_adapter(self, hand, mock_adapter):
        """拖拽使用 adapter.drag_to。"""
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await hand.human_drag(10, 20, 100, 200, duration=0.1)

        mock_adapter.drag_to.assert_called_once()
        call_args = mock_adapter.drag_to.call_args
        assert call_args[0] == (10, 20, 100, 200)


class TestHumanScroll:
    @pytest.mark.asyncio
    async def test_human_scroll_divided(self, hand, mock_adapter):
        """滚动被分成多段。"""
        # 强制总是分成 3 段
        with patch("random.randint", return_value=3):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await hand.human_scroll(clicks=6, direction="down")

        # 至少调用 3 次 scroll
        assert mock_adapter.scroll.call_count == 3


# ---------------------------------------------------------------------------
# 4. 键盘操作测试
# ---------------------------------------------------------------------------

class TestHumanType:
    @pytest.mark.asyncio
    async def test_human_type_calls_adapter(self, hand, mock_adapter):
        """human_type 对每个字符调用 adapter.type_text。"""
        # typo 概率设为 0，确保不打错
        hand._config.typo_probability = 0.0
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await hand.human_type("abc")

        assert mock_adapter.type_text.call_count == 3
        chars = [c[0][0] for c in mock_adapter.type_text.call_args_list]
        assert chars == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_human_type_with_typo(self, hand, mock_adapter):
        """打字时偶尔打错再删除。"""
        hand._config.typo_probability = 0.02

        # 让 random.random() 返回很小的值 → 触发 typo
        # 让 random.choice 返回 'x' → 打错的字符
        with patch("random.random", return_value=0.01), \
             patch("random.choice", return_value="x"), \
             patch("random.uniform", return_value=0.1), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await hand.human_type("a")

        # 应调用 type_text 两次：一次错误字符 'x'，一次正确字符 'a'
        assert mock_adapter.type_text.call_count == 2
        # 应调用 press_key("backspace") 一次来删除错误字符
        mock_adapter.press_key.assert_called_once_with("backspace")


class TestHumanPressKey:
    @pytest.mark.asyncio
    async def test_human_press_key_duration(self, hand, mock_adapter):
        """按键有随机保持时间。"""
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await hand.human_press_key("enter")

        mock_adapter.press_key.assert_called_once_with("enter")
        # 应该有 asyncio.sleep 调用（保持时间）
        assert mock_sleep.call_count > 0


class TestHumanHotkey:
    @pytest.mark.asyncio
    async def test_human_hotkey_sequence(self, hand, mock_adapter):
        """组合键按正确顺序按下和释放。"""
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await hand.human_hotkey("ctrl", "c")

        mock_adapter.hotkey.assert_called_once_with("ctrl", "c")
