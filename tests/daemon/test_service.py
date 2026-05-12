# -*- coding: utf-8 -*-
"""JavasService 单元测试。

所有涉及 start() 的测试都 mock 掉真实子系统（IPC、Tray、Hotkey、ChatWindow），
避免在测试环境中创建 Named Pipe / pystray / keyboard 等真实资源。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.daemon.service import JavasService, ServiceConfig, ServiceState


class TestServiceConfig:
    """ServiceConfig 测试。"""

    def test_default_values(self):
        cfg = ServiceConfig()
        assert cfg.pipe_name == "javasagent_pipe"
        assert cfg.autostart is False
        assert cfg.tray_enabled is True
        assert cfg.window_width == 600
        assert cfg.window_height == 400

    def test_custom_values(self):
        cfg = ServiceConfig(pipe_name="custom_pipe", autostart=True)
        assert cfg.pipe_name == "custom_pipe"
        assert cfg.autostart is True


class TestJavasServiceInit:
    """JavasService.__init__ 测试。"""

    def test_all_subsystems_none(self):
        svc = JavasService()
        assert svc._agent is None
        assert svc._voice_pipeline is None
        assert svc._ipc_server is None
        assert svc._tray is None
        assert svc._hotkey is None
        assert svc._chat_window is None

    def test_initial_state_stopped(self):
        svc = JavasService()
        assert svc.state == ServiceState.STOPPED

    def test_default_config(self):
        svc = JavasService()
        assert isinstance(svc.config, ServiceConfig)

    def test_custom_config(self):
        cfg = ServiceConfig(pipe_name="test_pipe")
        svc = JavasService(config=cfg)
        assert svc.config.pipe_name == "test_pipe"


def _mock_all_subsystems():
    """返回一个 dict，用于 mock 掉所有子系统的 start/stop。"""
    mock_ipc = MagicMock()
    mock_ipc.is_running = False
    mock_ipc.stop = MagicMock()
    mock_tray = MagicMock()
    mock_tray.stop = MagicMock()
    mock_hotkey = MagicMock()
    mock_hotkey.is_active = False
    mock_hotkey.stop = MagicMock()
    mock_window = MagicMock()
    mock_window.close = MagicMock()
    return {
        "ipc_server": mock_ipc,
        "tray": mock_tray,
        "hotkey": mock_hotkey,
        "chat_window": mock_window,
    }


class TestJavasServiceStartStop:
    """start / stop 测试。

    通过 mock 真实子系统避免创建 Named Pipe、pystray、keyboard 等资源。
    """

    @pytest.mark.asyncio
    async def test_start_without_subsystems(self):
        """无子系统时 start 不崩溃（mock 掉 import 和子系统创建）。"""
        svc = JavasService()
        mocks = _mock_all_subsystems()

        with patch.object(svc, "_start_ipc_server", new_callable=AsyncMock), \
             patch.object(svc, "_start_tray"), \
             patch.object(svc, "_start_hotkey"), \
             patch.object(svc, "_init_chat_window"):
            await svc.start()
            assert svc.state == ServiceState.RUNNING

    @pytest.mark.asyncio
    async def test_stop_after_start(self):
        """start 后 stop 正常完成。"""
        svc = JavasService()
        mocks = _mock_all_subsystems()

        with patch.object(svc, "_start_ipc_server", new_callable=AsyncMock), \
             patch.object(svc, "_start_tray"), \
             patch.object(svc, "_start_hotkey"), \
             patch.object(svc, "_init_chat_window"):
            await svc.start()

            # 手动设置 mock 子系统，这样 stop 会调用 mock 的 stop
            svc._ipc_server = mocks["ipc_server"]
            svc._tray = mocks["tray"]
            svc._hotkey = mocks["hotkey"]
            svc._chat_window = mocks["chat_window"]

            await svc.stop()
            assert svc.state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        """stop 可重复调用。"""
        svc = JavasService()
        await svc.stop()  # 未启动就 stop
        assert svc.state == ServiceState.STOPPED
        await svc.stop()  # 再次 stop
        assert svc.state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        """重复 start 不报错。"""
        svc = JavasService()

        with patch.object(svc, "_start_ipc_server", new_callable=AsyncMock), \
             patch.object(svc, "_start_tray"), \
             patch.object(svc, "_start_hotkey"), \
             patch.object(svc, "_init_chat_window"):
            await svc.start()
            await svc.start()  # 重复调用
            assert svc.state == ServiceState.RUNNING

    @pytest.mark.asyncio
    async def test_start_stop_cycle(self):
        """完整启动-停止循环。"""
        svc = JavasService()
        mocks = _mock_all_subsystems()

        for _ in range(2):
            with patch.object(svc, "_start_ipc_server", new_callable=AsyncMock), \
                 patch.object(svc, "_start_tray"), \
                 patch.object(svc, "_start_hotkey"), \
                 patch.object(svc, "_init_chat_window"):
                await svc.start()
                assert svc.state == ServiceState.RUNNING

            svc._ipc_server = mocks["ipc_server"]
            svc._tray = mocks["tray"]
            svc._hotkey = mocks["hotkey"]
            svc._chat_window = mocks["chat_window"]

            await svc.stop()
            assert svc.state == ServiceState.STOPPED


class TestJavasServiceStatus:
    """status() 测试。"""

    def test_status_when_stopped(self):
        svc = JavasService()
        s = svc.status()
        assert s["state"] == "stopped"
        assert s["agent"] is False
        assert s["voice_pipeline"] is False
        assert s["ipc_server"] is False
        assert s["tray"] is False
        assert s["hotkey"] is False
        assert s["chat_window"] is False

    @pytest.mark.asyncio
    async def test_status_when_running(self):
        svc = JavasService()

        with patch.object(svc, "_start_ipc_server", new_callable=AsyncMock), \
             patch.object(svc, "_start_tray"), \
             patch.object(svc, "_start_hotkey"), \
             patch.object(svc, "_init_chat_window"):
            await svc.start()
            s = svc.status()
            assert s["state"] == "running"
            # Agent 可能被 _start_agent 真正初始化（import src.main 成功时）
            # 只验证 status() 返回正确类型
            assert isinstance(s["agent"], bool)
