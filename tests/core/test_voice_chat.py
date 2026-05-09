"""VoiceChatLoop 语音对话循环测试。

测试语音对话引擎的初始化、配置、退出指令识别、
错误恢复、生命周期管理。所有 STT/TTS/Agent 调用均使用 Mock。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.voice_chat import VoiceChatConfig, VoiceChatLoop


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_agent() -> AsyncMock:
    """创建模拟的 BaseAgent。"""
    agent = AsyncMock(spec=["process", "initialize_memory", "close"])
    agent.process = AsyncMock(return_value="这是 Agent 的回复")
    return agent


def _make_mock_voice_ops() -> AsyncMock:
    """创建模拟的 VoiceOps。"""
    ops = AsyncMock()

    async def _execute(action: str, params: dict):
        if action == "speak":
            return {"status": "speaking", "text": params.get("text", "")}
        if action == "stop":
            return {"status": "stopped"}
        if action == "listen":
            return {"status": "timeout", "text": "", "timeout": 10.0}
        return {}

    ops.execute.side_effect = _execute
    ops._tts = MagicMock()
    ops._tts._speaking = False
    return ops


# ---------------------------------------------------------------------------
# 初始化与配置
# ---------------------------------------------------------------------------


class TestVoiceChatConfig:
    """VoiceChatConfig 配置测试。"""

    def test_default_config(self) -> None:
        config = VoiceChatConfig()
        assert config.wake_word == ""
        assert config.listen_timeout == 10.0
        assert "退出" in config.exit_commands
        assert "quit" in config.exit_commands

    def test_custom_config(self) -> None:
        config = VoiceChatConfig(wake_word="贾维斯", listen_timeout=5.0, exit_commands=["拜拜"])
        assert config.wake_word == "贾维斯"
        assert config.exit_commands == ["拜拜"]


class TestVoiceChatLoopInit:
    """VoiceChatLoop 初始化测试。"""

    def test_basic_init(self) -> None:
        agent, ops = _make_mock_agent(), _make_mock_voice_ops()
        loop = VoiceChatLoop(agent, ops)
        assert not loop.is_running
        assert loop.config.wake_word == ""

    def test_init_with_config(self) -> None:
        agent, ops = _make_mock_agent(), _make_mock_voice_ops()
        config = VoiceChatConfig(wake_word="贾维斯", tts_rate=5)
        loop = VoiceChatLoop(agent, ops, config)
        assert loop.config.wake_word == "贾维斯"

    def test_no_wake_word_means_activated(self) -> None:
        agent, ops = _make_mock_agent(), _make_mock_voice_ops()
        loop = VoiceChatLoop(agent, ops, VoiceChatConfig(wake_word=""))
        assert loop._wake_word_activated is True

    def test_with_wake_word_means_not_activated(self) -> None:
        agent, ops = _make_mock_agent(), _make_mock_voice_ops()
        loop = VoiceChatLoop(agent, ops, VoiceChatConfig(wake_word="贾维斯"))
        assert loop._wake_word_activated is False


# ---------------------------------------------------------------------------
# 退出指令识别
# ---------------------------------------------------------------------------


class TestExitCommandDetection:
    """退出指令检测测试。"""

    @pytest.mark.parametrize("text", ["退出", "再见", "quit", "exit", "goodbye", "QUIT", " 再见 "])
    def test_exit_commands(self, text: str) -> None:
        agent, ops = _make_mock_agent(), _make_mock_voice_ops()
        loop = VoiceChatLoop(agent, ops)
        assert loop._is_exit_command(text) is True

    @pytest.mark.parametrize("text", ["你好", "今天天气怎么样", "帮我写个代码"])
    def test_non_exit_commands(self, text: str) -> None:
        agent, ops = _make_mock_agent(), _make_mock_voice_ops()
        loop = VoiceChatLoop(agent, ops)
        assert loop._is_exit_command(text) is False

    def test_custom_exit_commands(self) -> None:
        agent, ops = _make_mock_agent(), _make_mock_voice_ops()
        loop = VoiceChatLoop(agent, ops, VoiceChatConfig(exit_commands=["拜拜"]))
        assert loop._is_exit_command("拜拜") is True
        assert loop._is_exit_command("quit") is False


# ---------------------------------------------------------------------------
# 唤醒词检测
# ---------------------------------------------------------------------------


class TestWakeWordDetection:
    """唤醒词检测测试。"""

    def test_contains_match(self) -> None:
        agent, ops = _make_mock_agent(), _make_mock_voice_ops()
        loop = VoiceChatLoop(agent, ops, VoiceChatConfig(wake_word="贾维斯"))
        assert loop._contains_wake_word("贾维斯你好") is True
        assert loop._contains_wake_word("你好") is False

    def test_case_insensitive(self) -> None:
        agent, ops = _make_mock_agent(), _make_mock_voice_ops()
        loop = VoiceChatLoop(agent, ops, VoiceChatConfig(wake_word="jarvis"))
        assert loop._contains_wake_word("Hey Jarvis") is True

    def test_strip_wake_word(self) -> None:
        agent, ops = _make_mock_agent(), _make_mock_voice_ops()
        loop = VoiceChatLoop(agent, ops, VoiceChatConfig(wake_word="贾维斯"))
        assert loop._strip_wake_word("贾维斯今天天气怎么样") == "今天天气怎么样"

    def test_empty_wake_word_always_matches(self) -> None:
        agent, ops = _make_mock_agent(), _make_mock_voice_ops()
        loop = VoiceChatLoop(agent, ops, VoiceChatConfig(wake_word=""))
        assert loop._contains_wake_word("任何文本") is True


# ---------------------------------------------------------------------------
# 文本提取
# ---------------------------------------------------------------------------


class TestExtractText:
    """STT 结果文本提取测试。"""

    def test_normal(self) -> None:
        assert VoiceChatLoop._extract_text({"status": "recognized", "text": "你好"}) == "你好"

    def test_empty(self) -> None:
        assert VoiceChatLoop._extract_text({"status": "timeout", "text": ""}) == ""

    def test_none_result(self) -> None:
        assert VoiceChatLoop._extract_text(None) == ""  # type: ignore

    def test_error_result(self) -> None:
        assert VoiceChatLoop._extract_text({"error": "unsupported"}) == ""

    def test_strips_whitespace(self) -> None:
        assert VoiceChatLoop._extract_text({"text": "  你好  "}) == "你好"


# ---------------------------------------------------------------------------
# 错误恢复
# ---------------------------------------------------------------------------


class TestErrorRecovery:
    """错误恢复测试。"""

    @pytest.mark.asyncio
    async def test_stt_error_does_not_crash(self) -> None:
        """STT 出错后循环不应崩溃。"""
        agent = _make_mock_agent()
        ops = _make_mock_voice_ops()
        call_count = 0

        async def _exec(action: str, params: dict):
            nonlocal call_count
            call_count += 1
            if action == "listen" and call_count <= 2:
                raise RuntimeError("STT 设备错误")
            if action == "listen":
                return {"status": "recognized", "text": "退出"}
            if action == "speak":
                return {"status": "speaking"}
            if action == "stop":
                return {"status": "stopped"}
            return {}

        ops.execute.side_effect = _exec
        loop = VoiceChatLoop(agent, ops, VoiceChatConfig(greeting=""))

        async def _auto_stop():
            await asyncio.sleep(5.0)
            if loop.is_running:
                await loop.stop()

        stop_task = asyncio.create_task(_auto_stop())
        await loop.start()
        stop_task.cancel()
        assert not loop.is_running

    @pytest.mark.asyncio
    async def test_tts_error_does_not_crash(self) -> None:
        """TTS 出错后循环不应崩溃。"""
        agent = _make_mock_agent()
        ops = _make_mock_voice_ops()

        async def _exec(action: str, params: dict):
            if action == "speak":
                raise RuntimeError("TTS 引擎错误")
            if action == "stop":
                return {"status": "stopped"}
            if action == "listen":
                return {"status": "recognized", "text": "退出"}
            return {}

        ops.execute.side_effect = _exec
        loop = VoiceChatLoop(agent, ops, VoiceChatConfig(greeting=""))
        await loop.start()
        assert not loop.is_running

    @pytest.mark.asyncio
    async def test_agent_error_returns_friendly_message(self) -> None:
        """Agent 处理失败时应返回友好提示。"""
        agent = _make_mock_agent()
        agent.process.side_effect = RuntimeError("Agent 内部错误")
        ops = _make_mock_voice_ops()
        spoken_texts: list[str] = []
        listen_seq = ["你好", "退出"]
        listen_idx = 0

        async def _exec(action: str, params: dict):
            nonlocal listen_idx
            if action == "speak":
                spoken_texts.append(params.get("text", ""))
                return {"status": "speaking"}
            if action == "stop":
                return {"status": "stopped"}
            if action == "listen":
                text = listen_seq[min(listen_idx, len(listen_seq) - 1)]
                listen_idx += 1
                return {"status": "recognized", "text": text}
            return {}

        ops.execute.side_effect = _exec
        loop = VoiceChatLoop(agent, ops, VoiceChatConfig(greeting=""))
        await loop.start()
        error_msgs = [t for t in spoken_texts if "抱歉" in t or "问题" in t]
        assert len(error_msgs) > 0


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------


class TestLifecycle:
    """start/stop 生命周期测试。"""

    @pytest.mark.asyncio
    async def test_start_sets_running(self) -> None:
        agent, ops = _make_mock_agent(), _make_mock_voice_ops()
        running_states: list[bool] = []

        async def _exec(action: str, params: dict):
            if action == "listen":
                running_states.append(loop.is_running)
                return {"status": "recognized", "text": "退出"}
            if action == "speak":
                return {"status": "speaking"}
            if action == "stop":
                return {"status": "stopped"}
            return {}

        ops.execute.side_effect = _exec
        loop = VoiceChatLoop(agent, ops, VoiceChatConfig(greeting=""))
        await loop.start()
        assert not loop.is_running
        assert True in running_states

    @pytest.mark.asyncio
    async def test_stop_stops_loop(self) -> None:
        agent, ops = _make_mock_agent(), _make_mock_voice_ops()
        listen_count = 0

        async def _exec(action: str, params: dict):
            nonlocal listen_count
            if action == "listen":
                listen_count += 1
                if listen_count >= 2:
                    await loop.stop()
                return {"status": "timeout", "text": ""}
            if action in ("speak", "stop"):
                return {"status": "ok"}
            return {}

        ops.execute.side_effect = _exec
        loop = VoiceChatLoop(agent, ops, VoiceChatConfig(greeting=""))
        await loop.start()
        assert not loop.is_running

    @pytest.mark.asyncio
    async def test_stop_when_not_running_is_safe(self) -> None:
        agent, ops = _make_mock_agent(), _make_mock_voice_ops()
        loop = VoiceChatLoop(agent, ops)
        await loop.stop()
        assert not loop.is_running


# ---------------------------------------------------------------------------
# 完整对话循环
# ---------------------------------------------------------------------------


class TestFullDialogLoop:
    """完整对话循环测试。"""

    @pytest.mark.asyncio
    async def test_listen_think_speak_cycle(self) -> None:
        agent = _make_mock_agent()
        agent.process = AsyncMock(return_value="今天天气晴朗")
        ops = _make_mock_voice_ops()
        responses: list[str] = []
        inputs: list[str] = []

        async def _exec(action: str, params: dict):
            if action == "listen":
                if not inputs:
                    inputs.append("done")
                    return {"status": "recognized", "text": "今天天气怎么样"}
                return {"status": "recognized", "text": "退出"}
            if action == "speak":
                responses.append(params.get("text", ""))
                return {"status": "speaking"}
            if action == "stop":
                return {"status": "stopped"}
            return {}

        ops.execute.side_effect = _exec
        loop = VoiceChatLoop(agent, ops, VoiceChatConfig(greeting=""))
        await loop.start()
        agent.process.assert_called_once_with("今天天气怎么样")
        assert "今天天气晴朗" in responses

    @pytest.mark.asyncio
    async def test_empty_input_is_ignored(self) -> None:
        agent = _make_mock_agent()
        ops = _make_mock_voice_ops()
        listen_count = 0

        async def _exec(action: str, params: dict):
            nonlocal listen_count
            if action == "listen":
                listen_count += 1
                if listen_count == 1:
                    return {"status": "timeout", "text": ""}
                return {"status": "recognized", "text": "退出"}
            if action in ("speak", "stop"):
                return {"status": "ok"}
            return {}

        ops.execute.side_effect = _exec
        loop = VoiceChatLoop(agent, ops, VoiceChatConfig(greeting=""))
        await loop.start()
        agent.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_greeting_and_farewell(self) -> None:
        agent = _make_mock_agent()
        ops = _make_mock_voice_ops()
        spoken: list[str] = []

        async def _exec(action: str, params: dict):
            if action == "speak":
                spoken.append(params.get("text", ""))
                return {"status": "speaking"}
            if action == "listen":
                return {"status": "recognized", "text": "退出"}
            if action == "stop":
                return {"status": "stopped"}
            return {}

        ops.execute.side_effect = _exec
        config = VoiceChatConfig(greeting="欢迎", farewell="再见老板")
        loop = VoiceChatLoop(agent, ops, config)
        await loop.start()
        assert "欢迎" in spoken
        assert "再见老板" in spoken

    @pytest.mark.asyncio
    async def test_state_callback_emitted(self) -> None:
        agent = _make_mock_agent()
        agent.process = AsyncMock(return_value="回复")
        ops = _make_mock_voice_ops()
        states: list[str] = []
        call_count = 0

        async def _exec(action: str, params: dict):
            nonlocal call_count
            if action == "listen":
                call_count += 1
                if call_count == 1:
                    return {"status": "recognized", "text": "你好"}
                return {"status": "recognized", "text": "退出"}
            if action in ("speak", "stop"):
                return {"status": "ok"}
            return {}

        ops.execute.side_effect = _exec
        loop = VoiceChatLoop(agent, ops, VoiceChatConfig(greeting=""))
        loop.set_state_callback(lambda s: states.append(s))
        await loop.start()
        assert "listening" in states
        assert "thinking" in states
        assert "speaking" in states

    @pytest.mark.asyncio
    async def test_wake_word_flow(self) -> None:
        agent = _make_mock_agent()
        agent.process = AsyncMock(return_value="天气晴")
        ops = _make_mock_voice_ops()
        listen_seq = ["今天天气", "贾维斯", "贾维斯 天气", "退出"]
        listen_idx = 0
        spoken: list[str] = []

        async def _exec(action: str, params: dict):
            nonlocal listen_idx
            if action == "listen":
                text = listen_seq[min(listen_idx, len(listen_seq) - 1)]
                listen_idx += 1
                return {"status": "recognized", "text": text}
            if action == "speak":
                spoken.append(params.get("text", ""))
                return {"status": "speaking"}
            if action == "stop":
                return {"status": "stopped"}
            return {}

        ops.execute.side_effect = _exec
        config = VoiceChatConfig(wake_word="贾维斯", greeting="")
        loop = VoiceChatLoop(agent, ops, config)
        await loop.start()
        assert "我在，请说。" in spoken
        agent.process.assert_called_with("天气")
