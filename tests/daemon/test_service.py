# -*- coding: utf-8 -*-
"""JavasService 单元测试。"""

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


class TestJavasServiceStartStop:
    """start / stop 测试。"""

    @pytest.mark.asyncio
    async def test_start_without_subsystems(self):
        """无子系统时 start 不崩溃。"""
        svc = JavasService()
        await svc.start()
        assert svc.state == ServiceState.RUNNING

    @pytest.mark.asyncio
    async def test_stop_after_start(self):
        svc = JavasService()
        await svc.start()
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
        await svc.start()
        await svc.start()  # 重复调用
        assert svc.state == ServiceState.RUNNING

    @pytest.mark.asyncio
    async def test_start_stop_cycle(self):
        """完整启动-停止循环。"""
        svc = JavasService()
        await svc.start()
        assert svc.state == ServiceState.RUNNING
        await svc.stop()
        assert svc.state == ServiceState.STOPPED
        # 可以再次启动
        await svc.start()
        assert svc.state == ServiceState.RUNNING
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
        await svc.start()
        s = svc.status()
        assert s["state"] == "running"
        # 骨架模式所有子系统仍为 None
        assert s["agent"] is False
        await svc.stop()
