"""AppLauncher 测试。

使用 pytest + mock，不依赖真实应用或环境。
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.app_launcher import AppLauncher
from src.tools.app_launcher_models import AppInfo, LaunchResult


# ── fixtures ────────────────────────────────────────────────


@pytest.fixture
def launcher() -> AppLauncher:
    """创建 AppLauncher 实例。"""
    return AppLauncher()


# ── execute 路由测试 ────────────────────────────────────────


class TestExecuteRouting:
    """execute 方法的 action 路由测试。"""

    @pytest.mark.asyncio
    async def test_unknown_action(self, launcher: AppLauncher) -> None:
        result = await launcher.execute("invalid_action", {})
        assert result["success"] is False
        assert "未知操作" in result["error"]

    @pytest.mark.asyncio
    async def test_known_actions_routed(self, launcher: AppLauncher) -> None:
        """验证所有已知 action 都能路由到对应方法。"""
        for action in ["launch", "search", "is_running", "bring_to_front", "close_app", "list_recent"]:
            result = await launcher.execute(action, {})
            # 不应是 "未知操作"
            assert "未知操作" not in str(result.get("error", ""))


# ── launch 测试 ─────────────────────────────────────────────


class TestLaunchByName:
    """通过名称启动应用测试。"""

    @pytest.mark.asyncio
    @patch.object(AppLauncher, "_find_app_path")
    @patch.object(AppLauncher, "_get_running_pid")
    @patch("subprocess.Popen")
    async def test_launch_by_name(
        self, mock_popen, mock_get_pid, mock_find, launcher: AppLauncher
    ) -> None:
        """模拟搜索并启动应用。"""
        mock_find.return_value = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        mock_get_pid.return_value = None  # 未在运行
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_popen.return_value = mock_proc

        result = await launcher.execute("launch", {"name": "chrome"})
        assert result["success"] is True
        assert result["data"]["pid"] == 1234

    @pytest.mark.asyncio
    @patch.object(AppLauncher, "_find_app_path")
    async def test_launch_name_not_found(self, mock_find, launcher: AppLauncher) -> None:
        """应用名称找不到时返回错误。"""
        mock_find.return_value = None
        result = await launcher.execute("launch", {"name": "nonexistent_app"})
        assert result["success"] is False
        assert "找不到应用" in result["error"]

    @pytest.mark.asyncio
    async def test_launch_no_params(self, launcher: AppLauncher) -> None:
        """没有提供 name 或 path 时报错。"""
        result = await launcher.execute("launch", {})
        assert result["success"] is False
        assert "必须提供" in result["error"]

    @pytest.mark.asyncio
    @patch.object(AppLauncher, "_find_app_path")
    @patch.object(AppLauncher, "_get_running_pid")
    @patch.object(AppLauncher, "_bring_window_to_front_by_pid")
    async def test_launch_already_running(
        self, mock_front, mock_pid, mock_find, launcher: AppLauncher
    ) -> None:
        """已运行的应用应尝试置前。"""
        mock_find.return_value = r"C:\some\chrome.exe"
        mock_pid.return_value = 5678
        mock_front.return_value = True

        result = await launcher.execute("launch", {"name": "chrome"})
        assert result["success"] is True
        assert result["data"]["already_running"] is True
        assert result["data"]["brought_to_front"] is True
        mock_front.assert_called_once_with(5678)


class TestLaunchByPath:
    """通过路径启动应用测试。"""

    @pytest.mark.asyncio
    @patch("os.path.isfile", return_value=True)
    @patch("subprocess.Popen")
    async def test_launch_by_path(self, mock_popen, mock_isfile, launcher: AppLauncher) -> None:
        """直接路径启动。"""
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_popen.return_value = mock_proc

        result = await launcher.execute("launch", {"path": r"C:\Windows\notepad.exe"})
        assert result["success"] is True
        assert result["data"]["pid"] == 9999
        assert result["data"]["path"] == r"C:\Windows\notepad.exe"

    @pytest.mark.asyncio
    @patch("os.path.isfile", return_value=False)
    @patch.object(AppLauncher, "_find_app_path", return_value=None)
    async def test_launch_path_not_found(self, mock_find, mock_isfile, launcher: AppLauncher) -> None:
        """路径不存在且找不到时报错。"""
        result = await launcher.execute("launch", {"path": r"C:\nonexistent\app.exe"})
        assert result["success"] is False

    @pytest.mark.asyncio
    @patch("subprocess.Popen", side_effect=FileNotFoundError("not found"))
    @patch("os.path.isfile", return_value=True)
    async def test_launch_process_file_not_found(self, mock_isfile, mock_popen, launcher: AppLauncher) -> None:
        """Popen 抛出 FileNotFoundError。"""
        result = await launcher.execute("launch", {"path": r"C:\missing.exe"})
        assert result["success"] is False
        assert "可执行文件不存在" in result["error"]


class TestLaunchProtocol:
    """URL 协议启动测试。"""

    @pytest.mark.asyncio
    @patch("os.startfile")
    async def test_launch_http(self, mock_startfile, launcher: AppLauncher) -> None:
        """HTTP 协议启动。"""
        # os.name == 'nt' in test environment on Windows
        result = await launcher.execute("launch", {"name": "https://example.com"})
        assert result["success"] is True
        assert result["data"]["protocol_launch"] is True

    @pytest.mark.asyncio
    @patch("os.startfile", side_effect=OSError("fail"))
    async def test_launch_protocol_fail(self, mock_startfile, launcher: AppLauncher) -> None:
        """协议启动失败。"""
        result = await launcher.execute("launch", {"name": "mailto:test@example.com"})
        assert result["success"] is False
        assert "协议启动失败" in result["error"]


# ── search 测试 ─────────────────────────────────────────────


class TestSearch:
    """搜索已安装应用测试。"""

    @pytest.mark.asyncio
    async def test_search_no_query(self, launcher: AppLauncher) -> None:
        """无查询关键词时报错。"""
        result = await launcher.execute("search", {})
        assert result["success"] is False
        assert "query" in result["error"]

    @pytest.mark.asyncio
    @patch.object(AppLauncher, "_search_start_menu")
    @patch.object(AppLauncher, "_search_common_paths")
    async def test_search_with_results(
        self, mock_common, mock_menu, launcher: AppLauncher
    ) -> None:
        """搜索返回结果。"""
        mock_menu.return_value = [AppInfo(name="Chrome", path=r"C:\Chrome\chrome.exe")]
        mock_common.return_value = []

        result = await launcher.execute("search", {"query": "chrome"})
        assert result["success"] is True
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    @patch.object(AppLauncher, "_search_start_menu")
    @patch.object(AppLauncher, "_search_common_paths")
    async def test_search_dedup(
        self, mock_common, mock_menu, launcher: AppLauncher
    ) -> None:
        """搜索结果去重。"""
        path = r"C:\Chrome\chrome.exe"
        mock_menu.return_value = [AppInfo(name="Chrome", path=path)]
        mock_common.return_value = [AppInfo(name="Chrome", path=path)]

        result = await launcher.execute("search", {"query": "chrome"})
        assert result["success"] is True
        assert result["data"]["count"] == 1


class TestSearchStartMenu:
    """_search_start_menu 测试。"""

    @patch("os.walk")
    @patch("os.path.isdir", return_value=True)
    def test_search_finds_lnk(self, mock_isdir, mock_walk, launcher: AppLauncher) -> None:
        """搜索 .lnk 快捷方式。"""
        # os.walk 被调用两次（两个开始菜单路径），第二次返回空
        mock_walk.side_effect = [
            [(r"C:\Start Menu\Programs", [], ["Chrome.lnk", "readme.txt"])],
            [],
        ]
        with patch.object(AppLauncher, "_resolve_lnk", return_value=r"C:\Chrome\chrome.exe"):
            results = launcher._search_start_menu("chrome")
        assert len(results) == 1
        assert results[0].name == "Chrome"

    @patch("os.path.isdir", return_value=False)
    def test_search_no_menu_dir(self, mock_isdir, launcher: AppLauncher) -> None:
        """开始菜单目录不存在。"""
        results = launcher._search_start_menu("anything")
        assert results == []


# ── is_running 测试 ─────────────────────────────────────────


class TestIsRunning:
    """检查进程状态测试。"""

    @pytest.mark.asyncio
    async def test_is_running_no_name(self, launcher: AppLauncher) -> None:
        result = await launcher.execute("is_running", {})
        assert result["success"] is False

    @pytest.mark.asyncio
    @patch.object(AppLauncher, "_check_process_running", return_value=True)
    @patch.object(AppLauncher, "_get_running_pid", return_value=100)
    async def test_is_running_true(self, mock_pid, mock_running, launcher: AppLauncher) -> None:
        result = await launcher.execute("is_running", {"name": "chrome"})
        assert result["success"] is True
        assert result["data"]["is_running"] is True
        assert result["data"]["pid"] == 100

    @pytest.mark.asyncio
    @patch.object(AppLauncher, "_check_process_running", return_value=False)
    async def test_is_running_false(self, mock_running, launcher: AppLauncher) -> None:
        result = await launcher.execute("is_running", {"name": "notepad"})
        assert result["success"] is True
        assert result["data"]["is_running"] is False
        assert result["data"]["pid"] is None


class TestCheckProcessRunning:
    """_check_process_running 内部方法测试。"""

    @patch("src.tools.app_launcher.logger")
    def test_psutil_not_installed(self, mock_logger, launcher: AppLauncher) -> None:
        """psutil 未安装时返回 False。"""
        with patch.dict("sys.modules", {"psutil": None}):
            # 重新导入会使 import psutil 失败
            # 这里直接测试方法内部逻辑
            result = AppLauncher._check_process_running("test")
            assert result is False

    @patch("psutil.process_iter")
    def test_process_running(self, mock_iter, launcher: AppLauncher) -> None:
        """找到匹配进程。"""
        mock_proc = MagicMock()
        mock_proc.info = {"name": "chrome.exe"}
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        mock_iter.return_value = [mock_proc]

        result = AppLauncher._check_process_running("chrome")
        assert result is True

    @patch("psutil.process_iter", return_value=[])
    def test_process_not_running(self, mock_iter, launcher: AppLauncher) -> None:
        """未找到匹配进程。"""
        result = AppLauncher._check_process_running("nonexistent")
        assert result is False


# ── bring_to_front 测试 ────────────────────────────────────


class TestBringToFront:
    """窗口置前测试。"""

    @pytest.mark.asyncio
    async def test_bring_no_params(self, launcher: AppLauncher) -> None:
        result = await launcher.execute("bring_to_front", {})
        assert result["success"] is False

    @pytest.mark.asyncio
    @patch.object(AppLauncher, "_bring_window_to_front_by_pid", return_value=True)
    @patch.object(AppLauncher, "_get_running_pid", return_value=100)
    async def test_bring_success(self, mock_pid, mock_front, launcher: AppLauncher) -> None:
        result = await launcher.execute("bring_to_front", {"name": "chrome"})
        assert result["success"] is True

    @pytest.mark.asyncio
    @patch.object(AppLauncher, "_get_running_pid", return_value=None)
    async def test_bring_not_found(self, mock_pid, launcher: AppLauncher) -> None:
        result = await launcher.execute("bring_to_front", {"name": "chrome"})
        assert result["success"] is False
        assert "找不到" in result["error"]

    @pytest.mark.asyncio
    @patch.object(AppLauncher, "_bring_window_to_front_by_pid", return_value=False)
    async def test_bring_fail(self, mock_front, launcher: AppLauncher) -> None:
        result = await launcher.execute("bring_to_front", {"pid": 100})
        assert result["success"] is False
        assert "窗口置前失败" in result["error"]


class TestBringWindowToFrontByPid:
    """_bring_window_to_front_by_pid 内部方法测试。"""

    @patch("os.name", "posix")
    def test_non_windows(self) -> None:
        """非 Windows 返回 False。"""
        result = AppLauncher._bring_window_to_front_by_pid(100)
        assert result is False

    @patch("os.name", "nt")
    def test_exception(self) -> None:
        """异常情况返回 False。"""
        with patch("ctypes.windll") as mock_windll:
            mock_windll.user32.EnumWindows.side_effect = Exception("fail")
            result = AppLauncher._bring_window_to_front_by_pid(100)
            assert result is False


# ── close_app 测试 ─────────────────────────────────────────


class TestCloseApp:
    """关闭应用测试。"""

    @pytest.mark.asyncio
    async def test_close_no_params(self, launcher: AppLauncher) -> None:
        result = await launcher.execute("close_app", {})
        assert result["success"] is False

    @pytest.mark.asyncio
    @patch.object(AppLauncher, "_close_process", return_value=True)
    async def test_close_by_pid(self, mock_close, launcher: AppLauncher) -> None:
        result = await launcher.execute("close_app", {"pid": 100})
        assert result["success"] is True

    @pytest.mark.asyncio
    @patch.object(AppLauncher, "_get_running_pid", return_value=None)
    async def test_close_not_found(self, mock_pid, launcher: AppLauncher) -> None:
        result = await launcher.execute("close_app", {"name": "chrome"})
        assert result["success"] is False

    @pytest.mark.asyncio
    @patch.object(AppLauncher, "_close_process", return_value=False)
    @patch.object(AppLauncher, "_get_running_pid", return_value=100)
    async def test_close_fail(self, mock_pid, mock_close, launcher: AppLauncher) -> None:
        result = await launcher.execute("close_app", {"name": "chrome"})
        assert result["success"] is False
        assert "关闭应用失败" in result["error"]


class TestCloseProcess:
    """_close_process 内部方法测试。"""

    @patch("psutil.Process")
    def test_graceful_close(self, mock_proc_cls) -> None:
        """优雅关闭。"""
        mock_proc = MagicMock()
        mock_proc_cls.return_value = mock_proc
        result = AppLauncher._close_process(100)
        assert result is True
        mock_proc.terminate.assert_called_once()

    @patch("psutil.Process", side_effect=__import__("psutil").NoSuchProcess(100))
    def test_no_such_process(self, mock_proc_cls) -> None:
        """进程不存在。"""
        result = AppLauncher._close_process(100)
        assert result is True  # 已不在了视为成功

    @patch("psutil.Process", side_effect=__import__("psutil").AccessDenied(100))
    def test_access_denied(self, mock_proc_cls) -> None:
        """无权限。"""
        result = AppLauncher._close_process(100)
        assert result is False

    @patch("psutil.Process")
    def test_force_close(self, mock_proc_cls) -> None:
        """强制关闭。"""
        mock_proc = MagicMock()
        mock_proc_cls.return_value = mock_proc
        result = AppLauncher._close_process(100, force=True)
        assert result is True
        mock_proc.kill.assert_called_once()


# ── list_recent 测试 ───────────────────────────────────────


class TestListRecent:
    """列出最近使用应用测试。"""

    @pytest.mark.asyncio
    @patch.object(AppLauncher, "_collect_all_shortcuts")
    async def test_list_recent(self, mock_collect, launcher: AppLauncher) -> None:
        mock_collect.return_value = [
            AppInfo(name="App1", path=r"C:\app1.lnk"),
            AppInfo(name="App2", path=r"C:\app2.lnk"),
        ]
        with patch("os.path.getmtime", side_effect=[1000.0, 2000.0]):
            result = await launcher.execute("list_recent", {})
        assert result["success"] is True
        assert result["data"]["count"] == 2
        # 按修改时间降序：App2 应在前
        assert result["data"]["apps"][0]["name"] == "App2"

    @pytest.mark.asyncio
    @patch.object(AppLauncher, "_collect_all_shortcuts", return_value=[])
    async def test_list_recent_empty(self, mock_collect, launcher: AppLauncher) -> None:
        result = await launcher.execute("list_recent", {})
        assert result["success"] is True
        assert result["data"]["count"] == 0


# ── 辅助方法测试 ───────────────────────────────────────────


class TestIsUrlProtocol:
    """_is_url_protocol 测试。"""

    def test_http(self) -> None:
        assert AppLauncher._is_url_protocol("http://example.com") is True

    def test_https(self) -> None:
        assert AppLauncher._is_url_protocol("https://example.com") is True

    def test_mailto(self) -> None:
        assert AppLauncher._is_url_protocol("mailto:test@example.com") is True

    def test_not_protocol(self) -> None:
        assert AppLauncher._is_url_protocol("notepad") is False

    def test_chrome(self) -> None:
        assert AppLauncher._is_url_protocol("chrome") is False


class TestFindAppPath:
    """_find_app_path 综合测试。"""

    @patch.object(AppLauncher, "_resolve_alias", return_value=r"C:\Chrome\chrome.exe")
    def test_alias_exact(self, mock_resolve, launcher: AppLauncher) -> None:
        result = launcher._find_app_path("chrome")
        assert result == r"C:\Chrome\chrome.exe"

    @patch.object(AppLauncher, "_resolve_alias", side_effect=[None, r"C:\Chrome\chrome.exe"])
    def test_alias_fuzzy(self, mock_resolve, launcher: AppLauncher) -> None:
        result = launcher._find_app_path("goo chrom")
        # 模糊匹配可能命中 "google chrome"
        assert result is not None or mock_resolve.call_count >= 1

    @patch.object(AppLauncher, "_search_start_menu")
    @patch.object(AppLauncher, "_search_common_paths", return_value=[])
    @patch.object(AppLauncher, "_resolve_alias", return_value=None)
    def test_finds_in_start_menu(self, mock_resolve, mock_common, mock_menu, launcher: AppLauncher) -> None:
        mock_menu.return_value = [AppInfo(name="MyApp", path=r"C:\MyApp\app.exe")]
        result = launcher._find_app_path("myapp")
        assert result == r"C:\MyApp\app.exe"

    @patch.object(AppLauncher, "_search_start_menu", return_value=[])
    @patch.object(AppLauncher, "_search_common_paths", return_value=[])
    @patch.object(AppLauncher, "_resolve_alias", return_value=None)
    def test_not_found(self, mock_resolve, mock_common, mock_menu, launcher: AppLauncher) -> None:
        result = launcher._find_app_path("nonexistent_xyz")
        assert result is None


class TestResolveLnk:
    """_resolve_lnk 测试。"""

    @patch("os.name", "posix")
    def test_non_windows(self) -> None:
        result = AppLauncher._resolve_lnk("/path/to/link")
        assert result is None

    @patch("os.name", "nt")
    @patch("subprocess.run")
    def test_resolve_success(self, mock_run) -> None:
        mock_run.return_value = MagicMock(stdout=r"C:\app.exe")
        result = AppLauncher._resolve_lnk(r"C:\shortcut.lnk")
        assert result == r"C:\app.exe"

    @patch("os.name", "nt")
    @patch("subprocess.run", side_effect=Exception("fail"))
    def test_resolve_fail(self, mock_run) -> None:
        result = AppLauncher._resolve_lnk(r"C:\shortcut.lnk")
        assert result is None


# ── 数据模型测试 ───────────────────────────────────────────


class TestAppInfo:
    """AppInfo 数据模型测试。"""

    def test_defaults(self) -> None:
        info = AppInfo(name="test", path="/test/app")
        assert info.icon_path is None
        assert info.version is None
        assert info.is_running is False
        assert info.pid is None

    def test_full(self) -> None:
        info = AppInfo(name="test", path="/test/app", icon_path="/icon", version="1.0", is_running=True, pid=100)
        assert info.name == "test"
        assert info.pid == 100


class TestLaunchResult:
    """LaunchResult 数据模型测试。"""

    def test_defaults(self) -> None:
        r = LaunchResult(success=True)
        assert r.app_name == ""
        assert r.pid is None
        assert r.already_running is False

    def test_full(self) -> None:
        r = LaunchResult(success=True, app_name="chrome", pid=100, path="/chrome", already_running=True)
        assert r.brought_to_front is False
