"""VoicePipeline 测试。Mock 所有硬件/外部服务。"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.voice.pipeline import PipelineState, VoicePipeline, VoicePipelineConfig


# ---------------------------------------------------------------------------
# Mock 工厂
# ---------------------------------------------------------------------------

class MockAgent:
    def __init__(self, response: str = "测试回复") -> None:
        self.response = response
        self.call_count = 0
        self.calls: list[str] = []
        self._raise = False

    async def process(self, text: str) -> str:
        self.call_count += 1
        self.calls.append(text)
        if self._raise:
            raise RuntimeError("Agent 异常")
        return self.response


class MockTTS:
    def __init__(self) -> None:
        self._speaking = False


class MockVoiceOps:
    """Mock VoiceOps。支持通过 on_listen 回调在 listen 返回后触发 stop。"""

    def __init__(self, texts: list[str] | None = None) -> None:
        self._texts = texts or ["你好"]
        self._idx = 0
        self.calls: list[tuple[str, dict]] = []
        self._tts = MockTTS()
        self.listen_count = 0
        self._pipeline: VoicePipeline | None = None
        self._stop_after_listen: int = 0  # 在第 N 次 listen 后自动 stop pipeline

    def bind(self, pipeline: VoicePipeline, stop_after: int = 0) -> None:
        self._pipeline = pipeline
        self._stop_after_listen = stop_after

    async def execute(self, action: str, params: dict) -> Any:
        # 让出控制权，确保事件循环可调度其他任务（如 delayed stop）
        await asyncio.sleep(0)
        self.calls.append((action, params))
        if action == "listen":
            self.listen_count += 1
            idx = min(self._idx, len(self._texts) - 1)
            text = self._texts[idx]
            self._idx += 1
            # 如果设置了自动 stop，在指定次数后通过 stop_event 通知退出
            if self._pipeline and self._stop_after_listen > 0:
                if self.listen_count >= self._stop_after_listen:
                    self._pipeline._stop_event.set()
            return {"status": "ok", "text": text}
        if action == "speak":
            self._tts._speaking = True
            self._tts._speaking = False
            return {"status": "ok"}
        if action == "stop":
            self._tts._speaking = False
            return {"status": "stopped"}
        return {"status": "ok"}


def _make(
    cfg: VoicePipelineConfig | None = None,
    texts: list[str] | None = None,
    agent_resp: str = "回复",
    stop_after: int = 0,
) -> tuple[VoicePipeline, MockAgent, MockVoiceOps]:
    agent = MockAgent(response=agent_resp)
    ops = MockVoiceOps(texts=texts)
    p = VoicePipeline(agent, ops, cfg)
    if stop_after > 0:
        ops.bind(p, stop_after=stop_after)
    return p, agent, ops


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

class TestConfig:
    def test_defaults(self):
        c = VoicePipelineConfig()
        assert c.wake_words == ["porcupine"]
        assert c.wake_word_enabled is True
        assert c.vad_threshold == 0.5
        assert c.continuous_mode is False
        assert c.greeting == "我在，请说。"
        assert c.farewell == "再见。"

    def test_custom(self):
        c = VoicePipelineConfig(wake_word_enabled=False, greeting="Hi")
        assert c.wake_word_enabled is False
        assert c.greeting == "Hi"


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------

class TestStateMachine:
    @pytest.mark.asyncio
    async def test_no_wake_transitions(self):
        cfg = VoicePipelineConfig(wake_word_enabled=False, continuous_mode=False)
        p, agent, ops = _make(cfg, stop_after=1)
        states: list[PipelineState] = []
        p.set_state_callback(lambda s: states.append(s))
        await asyncio.wait_for(p.start(), timeout=10.0)
        assert PipelineState.LISTENING in states
        assert PipelineState.PROCESSING in states

    @pytest.mark.asyncio
    async def test_wake_word_transitions(self):
        cfg = VoicePipelineConfig(wake_word_enabled=True, continuous_mode=False)
        p, agent, ops = _make(cfg, stop_after=1)
        states: list[PipelineState] = []
        p.set_state_callback(lambda s: states.append(s))
        with patch.object(p, "_wait_for_wake_word", new_callable=AsyncMock, return_value=True):
            await asyncio.wait_for(p.start(), timeout=10.0)
        assert PipelineState.LISTENING in states
        assert PipelineState.PROCESSING in states


# ---------------------------------------------------------------------------
# 免唤醒
# ---------------------------------------------------------------------------

class TestNoWake:
    @pytest.mark.asyncio
    async def test_skips_idle(self):
        cfg = VoicePipelineConfig(wake_word_enabled=False, continuous_mode=False)
        p, _, ops = _make(cfg, stop_after=1)
        await asyncio.wait_for(p.start(), timeout=10.0)
        speaks = [c for a, c in ops.calls if a == "speak"]
        assert any(c.get("text") == "我在，请说。" for c in speaks)


# ---------------------------------------------------------------------------
# 连续对话
# ---------------------------------------------------------------------------

class TestContinuous:
    @pytest.mark.asyncio
    async def test_multi_turn(self):
        cfg = VoicePipelineConfig(
            wake_word_enabled=False, continuous_mode=True, continuous_timeout=5.0
        )
        p, agent, ops = _make(cfg, texts=["第一句", "第二句", ""], stop_after=3)
        await asyncio.wait_for(p.start(), timeout=10.0)
        assert agent.call_count >= 2
        assert "第一句" in agent.calls
        assert "第二句" in agent.calls

    @pytest.mark.asyncio
    async def test_timeout_exits(self):
        cfg = VoicePipelineConfig(
            wake_word_enabled=False, continuous_mode=True, continuous_timeout=0.1
        )
        p, _, ops = _make(cfg, texts=[""])
        p._last_active_time = time.monotonic() - 10
        await asyncio.wait_for(p.start(), timeout=5.0)
        assert not p.is_running


# ---------------------------------------------------------------------------
# 打断
# ---------------------------------------------------------------------------

class TestInterruption:
    @pytest.mark.asyncio
    async def test_interrupt_disabled(self):
        cfg = VoicePipelineConfig(interruption_enabled=False)
        p, _, _ = _make(cfg)
        assert await p._check_interrupt() is False

    @pytest.mark.asyncio
    async def test_interrupt_runs_ok(self):
        cfg = VoicePipelineConfig(wake_word_enabled=False, interruption_enabled=True)
        p, _, ops = _make(cfg, stop_after=1)
        with patch.object(p, "_check_interrupt", new_callable=AsyncMock, return_value=True):
            await asyncio.wait_for(p.start(), timeout=10.0)
        # 不崩溃即通过


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------

class TestStop:
    @pytest.mark.asyncio
    async def test_stop_terminates(self):
        cfg = VoicePipelineConfig(wake_word_enabled=False)
        p, _, _ = _make(cfg)

        async def _delayed_stop():
            await asyncio.sleep(0.3)
            await p.stop()

        await asyncio.gather(p.start(), _delayed_stop())
        assert not p.is_running
        assert p.state == PipelineState.IDLE

    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        p, _, _ = _make()
        await p.stop()
        assert not p.is_running


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class TestErrors:
    @pytest.mark.asyncio
    async def test_agent_exception(self):
        cfg = VoicePipelineConfig(wake_word_enabled=False, continuous_mode=False)
        agent = MockAgent()
        agent._raise = True
        ops = MockVoiceOps(texts=["test"])
        p = VoicePipeline(agent, ops, cfg)
        ops.bind(p, stop_after=1)
        await asyncio.wait_for(p.start(), timeout=10.0)
        assert agent.call_count >= 1

    @pytest.mark.asyncio
    async def test_empty_stt(self):
        cfg = VoicePipelineConfig(wake_word_enabled=False, continuous_mode=False)
        p, agent, ops = _make(cfg, texts=[""], stop_after=1)
        await asyncio.wait_for(p.start(), timeout=10.0)
        assert agent.call_count == 0


# ---------------------------------------------------------------------------
# 退出指令
# ---------------------------------------------------------------------------

class TestExit:
    def test_exit_commands(self):
        p, _, _ = _make()
        assert p._is_exit("再见") is True
        assert p._is_exit("quit") is True
        assert p._is_exit("你好") is False
        assert p._is_exit("") is False

    @pytest.mark.asyncio
    async def test_exit_stops_pipeline(self):
        cfg = VoicePipelineConfig(wake_word_enabled=False, continuous_mode=False)
        ops = MockVoiceOps(texts=["再见"])
        agent = MockAgent()
        p = VoicePipeline(agent, ops, cfg)
        await asyncio.wait_for(p.start(), timeout=5.0)
        assert not p.is_running
        assert agent.call_count == 0
        speaks = [c for a, c in ops.calls if a == "speak"]
        assert any(c.get("text") == "再见。" for c in speaks)


# ---------------------------------------------------------------------------
# 属性
# ---------------------------------------------------------------------------

class TestProps:
    def test_initial(self):
        p, _, _ = _make()
        assert p.state == PipelineState.IDLE
        assert p.is_running is False

    def test_callback(self):
        p, _, _ = _make()
        seen: list[PipelineState] = []
        p.set_state_callback(lambda s: seen.append(s))
        p._set_state(PipelineState.LISTENING)
        assert PipelineState.LISTENING in seen


# ---------------------------------------------------------------------------
# 文本提取
# ---------------------------------------------------------------------------

class TestExtract:
    def test_various(self):
        p, _, _ = _make()
        assert p._extract_text({"text": "你好"}) == "你好"
        assert p._extract_text({"text": ""}) == ""
        assert p._extract_text({"error": "fail"}) == ""
        assert p._extract_text("直接") == "直接"
        assert p._extract_text(None) == ""
        assert p._extract_text(123) == ""
