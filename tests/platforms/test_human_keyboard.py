"""键盘输入人化测试 — Step 10。

覆盖 T10.1 和 T10.2 的全部功能点：
- 按键间隔随机化 30-120ms 正态分布
- 偶尔退格+重输（模拟打字纠错，概率 2%）
- 中英文切换增加延迟
- 剪贴板粘贴前等待 200-500ms
"""

from __future__ import annotations

import asyncio
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
    adapter.type_text = AsyncMock()
    adapter.press_key = AsyncMock()
    adapter.hotkey = AsyncMock()
    adapter.screenshot = AsyncMock(return_value=b"")
    return adapter


@pytest.fixture
def hand(mock_adapter):
    """默认配置 HumanHand。"""
    return HumanHand(mock_adapter)


@pytest.fixture
def hand_no_typo(mock_adapter):
    """无打字错误配置。"""
    config = HumanHandConfig(typo_probability=0.0)
    return HumanHand(mock_adapter, config=config)


# ════════════════════════════════════════════════════
# T10.1：键盘输入方法升级测试
# ════════════════════════════════════════════════════


class TestKeyIntervalNormalDistribution:
    """按键间隔正态分布测试（30-120ms）。"""

    @pytest.mark.asyncio
    async def test_interval_distribution_in_range(self, mock_adapter):
        """按键间隔在 30-120ms 范围内。"""
        config = HumanHandConfig(typo_probability=0.0)
        hand = HumanHand(mock_adapter, config=config)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await hand.human_type("abcdef")

        # 检查 type_text 调用中的 interval 参数
        calls = mock_adapter.type_text.call_args_list
        assert len(calls) == 6, f"应有 6 次 type_text 调用，实际 {len(calls)}"

        intervals = [c[1].get("interval", 0) for c in calls]
        for interval in intervals:
            assert 0.03 <= interval <= 0.12, (
                f"按键间隔 {interval * 1000:.0f}ms 不在 30-120ms 范围内"
            )

    @pytest.mark.asyncio
    async def test_interval_is_not_constant(self, mock_adapter):
        """按键间隔不是常量（有随机变化）。"""
        config = HumanHandConfig(typo_probability=0.0)
        hand = HumanHand(mock_adapter, config=config)

        sleep_values = []

        async def record_sleep(d):
            sleep_values.append(d)

        with patch("asyncio.sleep", side_effect=record_sleep):
            await hand.human_type("abcdefghij")

        key_intervals = [d for d in sleep_values if 0.01 <= d <= 0.20]
        if len(key_intervals) > 2:
            unique = set(round(d, 4) for d in key_intervals)
            assert len(unique) > 1, "按键间隔全部相同，没有随机化"

    @pytest.mark.asyncio
    async def test_interval_uses_gauss(self, mock_adapter):
        """按键间隔使用正态分布（gauss）生成。"""
        config = HumanHandConfig(typo_probability=0.0)
        hand = HumanHand(mock_adapter, config=config)

        gauss_call_args = []

        original_gauss = random.gauss

        def capture_gauss(mu, sigma):
            result = original_gauss(mu, sigma)
            gauss_call_args.append((mu, sigma, result))
            return result

        with patch("random.gauss", side_effect=capture_gauss):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await hand.human_type("abc")

        # 应使用 gauss 生成按键间隔
        assert len(gauss_call_args) >= 3, f"gauss 应被调用至少 3 次，实际 {len(gauss_call_args)}"

        # 验证均值在合理范围（30-120ms = 0.03-0.12）
        mus = [args[0] for args in gauss_call_args]
        for mu in mus:
            assert 0.03 <= mu <= 0.12, f"gauss 均值 {mu} 不在 30-120ms 范围"

    @pytest.mark.asyncio
    async def test_interval_clipped_to_range(self, mock_adapter):
        """按键间隔被裁剪到 30-120ms 范围。"""
        config = HumanHandConfig(typo_probability=0.0)
        hand = HumanHand(mock_adapter, config=config)

        sleep_values = []

        async def record_sleep(d):
            sleep_values.append(d)

        # 即使 gauss 返回极端值，间隔也应被裁剪
        with patch("asyncio.sleep", side_effect=record_sleep):
            with patch("random.gauss", return_value=-1.0):  # 极端负值
                await hand.human_type("ab")

        # 所有间隔应 >= 0.03 (30ms)
        for d in sleep_values:
            assert d >= 0.03, f"间隔 {d}s 小于最小值 30ms"


class TestTypoCorrection:
    """打字纠错模拟测试（退格+重输，概率 2%）。"""

    @pytest.mark.asyncio
    async def test_typo_triggers_backspace(self, mock_adapter):
        """打字错误时先输入错误字符，再退格，再输入正确字符。"""
        config = HumanHandConfig(typo_probability=1.0)  # 100% 触发
        hand = HumanHand(mock_adapter, config=config)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("random.choice", return_value="x"):
                await hand.human_type("a")

        # 应调用 type_text 两次：错误字符 + 正确字符
        assert mock_adapter.type_text.call_count == 2
        calls = mock_adapter.type_text.call_args_list
        assert calls[0][0][0] == "x"  # 错误字符
        assert calls[1][0][0] == "a"  # 正确字符

        # 应调用 press_key("backspace")
        mock_adapter.press_key.assert_any_call("backspace")

    @pytest.mark.asyncio
    async def test_typo_probability_two_percent(self, mock_adapter):
        """默认打字错误概率为 2%。"""
        config = HumanHandConfig()
        assert config.typo_probability == 0.02

    @pytest.mark.asyncio
    async def test_no_typo_for_spaces(self, mock_adapter):
        """空格不会触发打字错误。"""
        config = HumanHandConfig(typo_probability=1.0)  # 强制触发
        hand = HumanHand(mock_adapter, config=config)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("random.choice", return_value="x"):
                await hand.human_type(" ")

        # 空格是空白字符，不应触发 typo
        # 只应有一次 type_text 调用（空格本身），没有错误字符
        assert mock_adapter.type_text.call_count == 1
        call_args = mock_adapter.type_text.call_args
        assert call_args[0][0] == " "  # 只输入了空格

    @pytest.mark.asyncio
    async def test_typo_has_delay_after_wrong_char(self, mock_adapter):
        """打字错误后有延迟（意识到打错了）。"""
        config = HumanHandConfig(typo_probability=1.0)
        hand = HumanHand(mock_adapter, config=config)

        sleep_values = []

        async def record_sleep(d):
            sleep_values.append(d)

        with patch("asyncio.sleep", side_effect=record_sleep):
            with patch("random.choice", return_value="x"):
                await hand.human_type("a")

        # 应有一个"意识到打错了"的延迟（0.1-0.3s）
        recognition_delays = [d for d in sleep_values if 0.1 <= d <= 0.3]
        assert len(recognition_delays) >= 1, f"应有纠错延迟，实际 sleep: {sleep_values}"

    @pytest.mark.asyncio
    async def test_typo_has_delay_after_backspace(self, mock_adapter):
        """退格后有延迟（重新打字前）。"""
        config = HumanHandConfig(typo_probability=1.0)
        hand = HumanHand(mock_adapter, config=config)

        sleep_values = []

        async def record_sleep(d):
            sleep_values.append(d)

        with patch("asyncio.sleep", side_effect=record_sleep):
            with patch("random.choice", return_value="x"):
                await hand.human_type("a")

        # 应有一个退格后延迟（0.05-0.15s）
        backspace_delays = [d for d in sleep_values if 0.05 <= d <= 0.15]
        assert len(backspace_delays) >= 1, f"应有退格后延迟，实际 sleep: {sleep_values}"


class TestChineseEnglishSwitchDelay:
    """中英文切换增加延迟测试。"""

    @pytest.mark.asyncio
    async def test_mixed_input_has_switch_delay(self, mock_adapter):
        """中英文混合输入时有切换延迟。"""
        config = HumanHandConfig(typo_probability=0.0)
        hand = HumanHand(mock_adapter, config=config)

        sleep_values = []

        async def record_sleep(d):
            sleep_values.append(d)

        with patch("asyncio.sleep", side_effect=record_sleep):
            await hand.human_type("hello你好world")

        # 应有中英文切换延迟（0.15-0.40s）
        switch_delays = [d for d in sleep_values if 0.15 <= d <= 0.40]
        assert len(switch_delays) >= 1, (
            f"应有中英文切换延迟(0.15-0.40s)，实际 sleep: {sleep_values}"
        )

    @pytest.mark.asyncio
    async def test_pure_ascii_no_switch_delay(self, mock_adapter):
        """纯 ASCII 输入不应有中英文切换延迟。"""
        config = HumanHandConfig(typo_probability=0.0)
        hand = HumanHand(mock_adapter, config=config)

        sleep_values = []

        async def record_sleep(d):
            sleep_values.append(d)

        with patch("asyncio.sleep", side_effect=record_sleep):
            await hand.human_type("hello")

        # 不应有 0.15-0.40 范围的延迟（这是中英文切换延迟）
        switch_delays = [d for d in sleep_values if 0.15 <= d <= 0.40]
        assert len(switch_delays) == 0, (
            f"纯 ASCII 不应有中英文切换延迟，实际: {switch_delays}"
        )

    @pytest.mark.asyncio
    async def test_pure_chinese_no_switch_delay(self, mock_adapter):
        """纯中文输入不应有中英文切换延迟。"""
        config = HumanHandConfig(typo_probability=0.0)
        hand = HumanHand(mock_adapter, config=config)

        sleep_values = []

        async def record_sleep(d):
            sleep_values.append(d)

        with patch("asyncio.sleep", side_effect=record_sleep):
            await hand.human_type("你好世界")

        # 纯中文不应有中英文切换延迟
        switch_delays = [d for d in sleep_values if 0.15 <= d <= 0.40]
        assert len(switch_delays) == 0, (
            f"纯中文不应有中英文切换延迟，实际: {switch_delays}"
        )

    @pytest.mark.asyncio
    async def test_ascii_to_chinese_triggers_switch(self, mock_adapter):
        """从 ASCII 切换到中文触发切换延迟。"""
        config = HumanHandConfig(typo_probability=0.0)
        hand = HumanHand(mock_adapter, config=config)

        sleep_values = []

        async def record_sleep(d):
            sleep_values.append(d)

        with patch("asyncio.sleep", side_effect=record_sleep):
            await hand.human_type("a中")

        switch_delays = [d for d in sleep_values if 0.15 <= d <= 0.40]
        assert len(switch_delays) >= 1, "ASCII→中文应有切换延迟"

    @pytest.mark.asyncio
    async def test_chinese_to_ascii_triggers_switch(self, mock_adapter):
        """从中文切换到 ASCII 触发切换延迟。"""
        config = HumanHandConfig(typo_probability=0.0)
        hand = HumanHand(mock_adapter, config=config)

        sleep_values = []

        async def record_sleep(d):
            sleep_values.append(d)

        with patch("asyncio.sleep", side_effect=record_sleep):
            await hand.human_type("中a")

        switch_delays = [d for d in sleep_values if 0.15 <= d <= 0.40]
        assert len(switch_delays) >= 1, "中文→ASCII 应有切换延迟"


# ════════════════════════════════════════════════════
# T10.2：剪贴板输入延迟测试
# ════════════════════════════════════════════════════


class TestClipboardPasteDelay:
    """剪贴板粘贴延迟测试。"""

    @pytest.mark.asyncio
    async def test_human_paste_has_pre_delay(self, mock_adapter):
        """粘贴前有 200-500ms 延迟。"""
        config = HumanHandConfig(typo_probability=0.0)
        hand = HumanHand(mock_adapter, config=config)

        sleep_values = []

        async def record_sleep(d):
            sleep_values.append(d)

        with patch("asyncio.sleep", side_effect=record_sleep):
            await hand.human_paste("测试文本")

        # 第一个 sleep 应该是粘贴前延迟（200-500ms = 0.2-0.5）
        if sleep_values:
            pre_delay = sleep_values[0]
            assert 0.2 <= pre_delay <= 0.5, (
                f"粘贴前延迟应为 200-500ms，实际: {pre_delay * 1000:.0f}ms"
            )

    @pytest.mark.asyncio
    async def test_human_paste_calls_hotkey(self, mock_adapter):
        """粘贴调用 Ctrl+V 热键。"""
        config = HumanHandConfig(typo_probability=0.0)
        hand = HumanHand(mock_adapter, config=config)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await hand.human_paste("文本")

        mock_adapter.hotkey.assert_called_with("ctrl", "v")

    @pytest.mark.asyncio
    async def test_human_paste_uses_clipboard_copy(self, mock_adapter):
        """粘贴先复制文本到剪贴板。"""
        config = HumanHandConfig(typo_probability=0.0)
        hand = HumanHand(mock_adapter, config=config)

        copied_text = None

        def mock_copy(text):
            nonlocal copied_text
            copied_text = text

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("pyperclip.copy", side_effect=mock_copy):
                await hand.human_paste("要粘贴的文本")

        assert copied_text == "要粘贴的文本"

    @pytest.mark.asyncio
    async def test_human_paste_delay_in_range(self, mock_adapter):
        """粘贴前延迟在 200-500ms 范围内。"""
        config = HumanHandConfig(typo_probability=0.0)
        hand = HumanHand(mock_adapter, config=config)

        delays = []

        async def record_sleep(d):
            delays.append(d)

        # 运行多次，验证范围
        for _ in range(10):
            delays.clear()
            mock_adapter.reset_mock()

            with patch("asyncio.sleep", side_effect=record_sleep):
                with patch("pyperclip.copy"):
                    await hand.human_paste("x")

            if delays:
                assert 0.2 <= delays[0] <= 0.5, (
                    f"粘贴前延迟 {delays[0]} 超出 200-500ms"
                )


class TestPressKeyHumanized:
    """按键人化测试。"""

    @pytest.mark.asyncio
    async def test_press_key_has_pre_delay(self, mock_adapter):
        """按键前有微小延迟。"""
        config = HumanHandConfig(typo_probability=0.0)
        hand = HumanHand(mock_adapter, config=config)

        sleep_values = []

        async def record_sleep(d):
            sleep_values.append(d)

        with patch("asyncio.sleep", side_effect=record_sleep):
            await hand.human_press_key("enter")

        # 应有按键后延迟（0.05-0.15s）
        post_delays = [d for d in sleep_values if 0.05 <= d <= 0.15]
        assert len(post_delays) >= 1, f"应有按键延迟，实际: {sleep_values}"

    @pytest.mark.asyncio
    async def test_hotkey_has_pre_and_post_delay(self, mock_adapter):
        """组合键有前置和后置延迟。"""
        config = HumanHandConfig(typo_probability=0.0)
        hand = HumanHand(mock_adapter, config=config)

        sleep_values = []

        async def record_sleep(d):
            sleep_values.append(d)

        with patch("asyncio.sleep", side_effect=record_sleep):
            await hand.human_hotkey("ctrl", "c")

        # 前置延迟（0.03-0.08s）
        pre_delays = [d for d in sleep_values if 0.03 <= d <= 0.08]
        assert len(pre_delays) >= 1, f"应有前置延迟，实际: {sleep_values}"

        # 后置延迟（0.05-0.15s）
        post_delays = [d for d in sleep_values if 0.05 <= d <= 0.15]
        assert len(post_delays) >= 1, f"应有后置延迟，实际: {sleep_values}"
