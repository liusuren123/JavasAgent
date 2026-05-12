# -*- coding: utf-8 -*-
"""后台服务集成测试。

测试 JavasService 完整生命周期、IPC handler、CLI 命令参数解析。
所有外部依赖（Agent、pywin32、pystray、keyboard、tkinter）均 mock。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.daemon.service import JavasService, ServiceConfig, ServiceState
from src.daemon.ipc_protocol import (
    METHOD_CHAT,
    METHOD_STATUS,
    METHOD_STOP,
    METHOD_VOICE_TOGGLE,
    METHOD_SHOW_WINDOW,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def svc_config():
    """测试用 ServiceConfig。"""
    return ServiceConfig(
        pipe_name="test_pipe",
        tray_enabled=False,
        tray_tooltip="Test",
        hotkeys={
            "chat": "ctrl+alt+j",
            "voice_toggle": "ctrl+alt+v",
            "stop_task": "ctrl+alt+s",
        },
    )


@pytest.fixture
def svc(svc_config):
    """JavasService 实例。"""
    return JavasService(config=svc_config)


# ---------------------------------------------------------------------------
# JavasService 生命周期
# ---------------------------------------------------------------------------

class TestServiceLifecycle:
    """服务完整 start → stop 流程。"""

    @pytest.mark.asyncio
    async def test_start_stop_full(self, svc):
        """完整 start → stop 不崩溃（所有子系统 mock）。"""
        with patch("src.main.create_agent", side_effect=Exception("no agent")):
            with patch("src.daemon.service.IPCServer") as MockIPC, \
                 patch("src.daemon.service.HotkeyManager") as MockHK, \
                 patch("src.daemon.service.ChatWindow") as MockWin:

                # 配置 mock
                mock_ipc = MagicMock()
                mock_ipc.is_running = True
                MockIPC.return_value = mock_ipc

                mock_hk = MagicMock()
                mock_hk.is_active = True
                MockHK.return_value = mock_hk

                mock_win = MagicMock()
                MockWin.return_value = mock_win

                await svc.start()

                assert svc.state == ServiceState.RUNNING
                assert svc.is_running is True

                # IPC 应注册了 handler
                assert mock_ipc.register_handler.call_count == 5
                registered_methods = {
                    call.args[0] for call in mock_ipc.register_handler.call_args_list
                }
                assert METHOD_CHAT in registered_methods
                assert METHOD_STATUS in registered_methods
                assert METHOD_STOP in registered_methods
                assert METHOD_VOICE_TOGGLE in registered_methods
                assert METHOD_SHOW_WINDOW in registered_methods

                await svc.stop()
                assert svc.state == ServiceState.STOPPED
                assert svc.is_running is False

    @pytest.mark.asyncio
    async def test_start_idempotent(self, svc):
        """重复 start 不报错。"""
        with patch("src.main.create_agent", side_effect=Exception("no agent")), \
             patch("src.daemon.service.IPCServer"), \
             patch("src.daemon.service.HotkeyManager"), \
             patch("src.daemon.service.ChatWindow"):
            await svc.start()
            await svc.start()  # 不崩溃

        assert svc.state == ServiceState.RUNNING
        await svc.stop()

    @pytest.mark.asyncio
    async def test_stop_when_stopped(self, svc):
        """在 STOPPED 状态 stop 不报错。"""
        await svc.stop()
        await svc.stop()

    @pytest.mark.asyncio
    async def test_start_with_agent(self, svc):
        """Agent 成功创建时状态正确。"""
        mock_agent = MagicMock()
        with patch("src.main.create_agent", return_value=mock_agent), \
             patch("src.daemon.service.IPCServer"), \
             patch("src.daemon.service.HotkeyManager"), \
             patch("src.daemon.service.ChatWindow"):
            await svc.start()

        assert svc._agent is mock_agent
        await svc.stop()


# ---------------------------------------------------------------------------
# IPC Handler
# ---------------------------------------------------------------------------

class TestIPCHandlers:
    """IPC handler 单元测试。"""

    def test_handle_status(self, svc):
        """status handler 返回正确结构。"""
        result = svc._handle_status({})
        assert "state" in result
        assert "agent" in result
        assert "ipc_server" in result
        assert "tray" in result
        assert "hotkey" in result
        assert "chat_window" in result

    def test_handle_chat_no_agent(self, svc):
        """Agent 未就绪时返回错误。"""
        result = svc._handle_chat({"text": "你好"})
        assert result["status"] == "error"
        assert "未就绪" in result["message"]

    def test_handle_chat_empty_text(self, svc):
        """空消息返回错误。"""
        svc._agent = MagicMock()
        result = svc._handle_chat({"text": ""})
        assert result["status"] == "error"

    def test_handle_chat_success(self, svc):
        """正常聊天返回结果。"""
        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(return_value="你好，我是 JavasAgent")
        svc._agent = mock_agent

        result = svc._handle_chat({"text": "你好"})
        assert result["status"] == "ok"
        assert "JavasAgent" in result["response"]

    def test_handle_chat_exception(self, svc):
        """Agent 处理异常时返回错误。"""
        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(side_effect=Exception("LLM 连接失败"))
        svc._agent = mock_agent

        result = svc._handle_chat({"text": "你好"})
        assert result["status"] == "error"

    def test_handle_voice_toggle(self, svc):
        """语音切换。"""
        assert svc._voice_enabled is False

        result1 = svc._handle_voice_toggle({})
        assert result1["status"] == "ok"
        assert result1["voice_enabled"] is True
        assert svc._voice_enabled is True

        result2 = svc._handle_voice_toggle({})
        assert result2["voice_enabled"] is False
        assert svc._voice_enabled is False

    def test_handle_show_window_no_window(self, svc):
        """窗口未初始化时返回错误。"""
        result = svc._handle_show_window({})
        assert result["status"] == "error"

    def test_handle_show_window_ok(self, svc):
        """窗口已初始化时显示。"""
        svc._chat_window = MagicMock()
        result = svc._handle_show_window({})
        assert result["status"] == "ok"
        svc._chat_window.show.assert_called_once()

    def test_handle_stop(self, svc):
        """stop handler 返回确认。"""
        # 不真正停止（需要 event loop），只检查返回值
        result = svc._handle_stop({})
        assert result["status"] == "ok"
        assert "停止" in result["message"]


# ---------------------------------------------------------------------------
# ServiceConfig
# ---------------------------------------------------------------------------

class TestServiceConfig:
    """ServiceConfig 测试。"""

    def test_default_values(self):
        config = ServiceConfig()
        assert config.pipe_name == "javasagent_pipe"
        assert config.autostart is False
        assert config.tray_enabled is True
        assert config.window_width == 600
        assert config.window_height == 400
        assert len(config.hotkeys) == 3

    def test_custom_values(self):
        config = ServiceConfig(
            pipe_name="custom_pipe",
            autostart=True,
            tray_enabled=False,
        )
        assert config.pipe_name == "custom_pipe"
        assert config.autostart is True
        assert config.tray_enabled is False


# ---------------------------------------------------------------------------
# ServiceState
# ---------------------------------------------------------------------------

class TestServiceState:
    """ServiceState 测试。"""

    def test_values(self):
        assert ServiceState.STOPPED.value == "stopped"
        assert ServiceState.STARTING.value == "starting"
        assert ServiceState.RUNNING.value == "running"
        assert ServiceState.STOPPING.value == "stopping"
        assert ServiceState.ERROR.value == "error"


# ---------------------------------------------------------------------------
# Tray 回调集成
# ---------------------------------------------------------------------------

class TestTrayCallbacks:
    """托盘菜单回调测试。"""

    def test_on_tray_chat(self, svc):
        """托盘打开对话窗口。"""
        svc._chat_window = MagicMock()
        svc._on_tray_chat()
        svc._chat_window.show.assert_called_once()

    def test_on_tray_voice_toggle(self, svc):
        """托盘切换语音。"""
        svc._on_tray_voice_toggle()
        assert svc._voice_enabled is True

    def test_on_tray_quit_without_loop(self, svc):
        """无 event loop 时退出不崩溃。"""
        svc._on_tray_quit()  # loop is None，应安全跳过
