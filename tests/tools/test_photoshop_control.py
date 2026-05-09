"""PhotoshopControl 测试。

使用 mock 模拟 COM 对象，验证 Photoshop 控制工具的核心逻辑。
不依赖 Photoshop 真正运行。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.tools.photoshop_control import PhotoshopControl


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def ps(tmp_path: Path) -> PhotoshopControl:
    """创建使用临时目录的 PhotoshopControl 实例。"""
    return PhotoshopControl(workspace=str(tmp_path))


@pytest.fixture
def mock_app():
    """创建一个模拟的 Photoshop COM 对象。"""
    app = MagicMock()
    app.ActiveDocument.Name = "test.psd"
    app.ActiveDocument.FullName = "C:\\test\\test.psd"
    app.ActiveDocument.Width = 1920
    app.ActiveDocument.Height = 1080
    app.ActiveDocument.Resolution = 72
    app.ActiveDocument.Mode = 5  # RGB
    app.ActiveDocument.BitsPerChannel = 8
    # 模拟图层迭代
    layer1 = MagicMock()
    layer1.Name = "Background"
    layer1.Visible = True
    layer1.Opacity = 100
    layer2 = MagicMock()
    layer2.Name = "Layer 1"
    layer2.Visible = False
    layer2.Opacity = 80
    # ArtLayers 和 LayerSets 需要同时支持迭代和 .Count
    art_layers = MagicMock()
    art_layers.__iter__ = MagicMock(return_value=iter([layer1, layer2]))
    art_layers.Count = 3
    layer_sets = MagicMock()
    layer_sets.__iter__ = MagicMock(return_value=iter([]))
    layer_sets.Count = 1
    app.ActiveDocument.ArtLayers = art_layers
    app.ActiveDocument.LayerSets = layer_sets
    # SaveOptions
    app.SaveOptions.pngFormat.return_value = MagicMock()
    app.SaveOptions.jpegFormat.return_value = MagicMock()
    app.SaveOptions.pdfFormat.return_value = MagicMock()
    app.SaveOptions.photoshopFormat.return_value = MagicMock()
    # ActionDescriptor
    app.ActionDescriptor.return_value = MagicMock()
    app.ActionReference.return_value = MagicMock()
    app.charIDToTypeID.side_effect = lambda s: hash(s) & 0xFFFFFFFF
    app.stringIDToTypeID.side_effect = lambda s: hash(s) & 0xFFFFFFFF
    return app


# ======================================================================
# 连接错误处理
# ======================================================================


class TestPhotoshopNotAvailable:
    """Photoshop 不可用时的错误处理。"""

    @pytest.mark.asyncio
    async def test_not_windows(self, ps: PhotoshopControl) -> None:
        """非 Windows 平台应返回友好错误。"""
        with patch.object(sys, "platform", "darwin"):
            result = await ps.execute("open_document", {"path": "test.psd"})
            assert "error" in result
            assert "Windows" in result["error"]

    @pytest.mark.asyncio
    async def test_pywin32_not_installed(self, ps: PhotoshopControl) -> None:
        """pywin32 未安装时应返回安装提示。"""
        with patch.object(sys, "platform", "win32"):
            with patch.dict(sys.modules, {"win32com": None, "win32com.client": None}):
                result = await ps.execute("open_document", {"path": "test.psd"})
                assert "error" in result
                assert "pywin32" in result["error"]

    @pytest.mark.asyncio
    async def test_photoshop_not_running(self, ps: PhotoshopControl) -> None:
        """Photoshop 未运行时应返回连接错误。"""
        with patch.object(sys, "platform", "win32"):
            # 创建测试文件，确保能通过文件存在检查
            workspace = ps._workspace
            test_file = workspace / "test.psd"
            test_file.write_bytes(b"fake")
            mock_win32com = MagicMock()
            mock_win32com.client.GetActiveObject.side_effect = Exception("Not found")
            with patch.dict(sys.modules, {"win32com": mock_win32com, "win32com.client": mock_win32com.client}):
                result = await ps.execute("open_document", {"path": "test.psd"})
                assert "error" in result
                assert "无法连接" in result["error"] or "Photoshop" in result["error"]


# ======================================================================
# Action 映射
# ======================================================================


class TestActionMapping:
    """验证所有 action 的 handler 映射。"""

    @pytest.mark.asyncio
    async def test_unknown_action(self, ps: PhotoshopControl) -> None:
        """未知操作应返回错误和可用操作列表。"""
        result = await ps.execute("nonexistent_action", {})
        assert "error" in result
        assert "未知操作" in result["error"]
        assert "available_actions" in result

    @pytest.mark.asyncio
    async def test_all_actions_listed(self, ps: PhotoshopControl) -> None:
        """所有 8 个操作都应出现在可用列表中。"""
        result = await ps.execute("bogus", {})
        actions = result.get("available_actions", [])
        expected = [
            "apply_filter", "close_document", "export_image",
            "get_document_info", "open_document", "resize",
            "run_action", "save_document",
        ]
        assert sorted(actions) == sorted(expected)


# ======================================================================
# 路径安全
# ======================================================================


class TestPathSafety:
    """路径安全检查测试。"""

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, ps: PhotoshopControl) -> None:
        """路径遍历应被阻止。"""
        result = await ps.execute("export_image", {
            "path": "../../etc/secret.png",
            "format": "png",
        })
        # 即使 Photoshop 未运行，路径检查应先于 COM 调用
        assert "error" in result

    @pytest.mark.asyncio
    async def test_save_path_traversal_blocked(self, ps: PhotoshopControl) -> None:
        """另存为时的路径遍历也应被阻止。"""
        result = await ps.execute("save_document", {
            "path": "../../../tmp/evil.psd",
        })
        assert "error" in result


# ======================================================================
# Mock COM 操作测试
# ======================================================================


class TestOpenDocument:
    """打开文档测试。"""

    @pytest.mark.asyncio
    async def test_open_missing_path_param(self, ps: PhotoshopControl) -> None:
        """缺少 path 参数应报错。"""
        result = await ps.execute("open_document", {})
        assert "error" in result
        assert "path" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_open_nonexistent_file(self, ps: PhotoshopControl) -> None:
        """文件不存在应报错。"""
        result = await ps.execute("open_document", {"path": "nonexistent.psd"})
        assert "error" in result
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_open_success(self, ps: PhotoshopControl, mock_app: MagicMock, tmp_path: Path) -> None:
        """成功打开文件。"""
        # 创建测试文件
        test_file = tmp_path / "test.psd"
        test_file.write_bytes(b"fake psd content")
        mock_app.Open.return_value = mock_app.ActiveDocument

        ps._app = mock_app
        ps._connected = True

        result = await ps.execute("open_document", {"path": "test.psd"})
        assert result["status"] == "opened"
        assert "document_name" in result
        mock_app.Open.assert_called_once()


class TestSaveDocument:
    """保存文档测试。"""

    @pytest.mark.asyncio
    async def test_save_in_place(self, ps: PhotoshopControl, mock_app: MagicMock) -> None:
        """原地保存。"""
        ps._app = mock_app
        ps._connected = True
        result = await ps.execute("save_document", {})
        assert result["status"] == "saved"
        mock_app.ActiveDocument.Save.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_as(self, ps: PhotoshopControl, mock_app: MagicMock, tmp_path: Path) -> None:
        """另存为新路径。"""
        ps._app = mock_app
        ps._connected = True
        result = await ps.execute("save_document", {"path": "output.psd"})
        assert result["status"] == "saved"
        assert "path" in result


class TestExportImage:
    """导出图像测试。"""

    @pytest.mark.asyncio
    async def test_export_missing_path(self, ps: PhotoshopControl) -> None:
        """缺少路径应报错。"""
        result = await ps.execute("export_image", {"format": "png"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_export_unsupported_format(self, ps: PhotoshopControl) -> None:
        """不支持的格式应报错。"""
        result = await ps.execute("export_image", {"path": "out.xxx", "format": "webp"})
        assert "error" in result
        assert "不支持" in result["error"]

    @pytest.mark.asyncio
    async def test_export_success(self, ps: PhotoshopControl, mock_app: MagicMock, tmp_path: Path) -> None:
        """成功导出。"""
        ps._app = mock_app
        ps._connected = True
        result = await ps.execute("export_image", {"path": "output.png", "format": "png"})
        assert result["status"] == "exported"
        assert result["format"] == "png"


class TestRunAction:
    """执行 Photoshop Action 测试。"""

    @pytest.mark.asyncio
    async def test_missing_action_name(self, ps: PhotoshopControl) -> None:
        """缺少 action_name 应报错。"""
        result = await ps.execute("run_action", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_run_action_success(self, ps: PhotoshopControl, mock_app: MagicMock) -> None:
        """成功执行 Action。"""
        ps._app = mock_app
        ps._connected = True
        result = await ps.execute("run_action", {"action_name": "MyAction", "action_set": "Default"})
        assert result["status"] == "action_executed"
        assert result["action_name"] == "MyAction"


class TestApplyFilter:
    """应用滤镜测试。"""

    @pytest.mark.asyncio
    async def test_missing_filter_name(self, ps: PhotoshopControl) -> None:
        """缺少 filter_name 应报错。"""
        result = await ps.execute("apply_filter", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_apply_filter_success(self, ps: PhotoshopControl, mock_app: MagicMock) -> None:
        """成功应用滤镜。"""
        ps._app = mock_app
        ps._connected = True
        result = await ps.execute("apply_filter", {
            "filter_name": "gaussian_blur",
            "radius": 10.0,
        })
        assert result["status"] == "filter_applied"


class TestResize:
    """调整尺寸测试。"""

    @pytest.mark.asyncio
    async def test_missing_dimensions(self, ps: PhotoshopControl) -> None:
        """缺少宽高应报错。"""
        result = await ps.execute("resize", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_dimensions(self, ps: PhotoshopControl) -> None:
        """无效宽高应报错。"""
        result = await ps.execute("resize", {"width": -1, "height": 100})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_resize_image(self, ps: PhotoshopControl, mock_app: MagicMock) -> None:
        """成功调整图像大小。"""
        ps._app = mock_app
        ps._connected = True
        result = await ps.execute("resize", {"width": 800, "height": 600})
        assert result["status"] == "resized"
        assert result["new_size"] == [800, 600]

    @pytest.mark.asyncio
    async def test_resize_canvas(self, ps: PhotoshopControl, mock_app: MagicMock) -> None:
        """成功调整画布大小。"""
        ps._app = mock_app
        ps._connected = True
        result = await ps.execute("resize", {"width": 2000, "height": 1500, "mode": "canvas"})
        assert result["status"] == "resized"
        assert result["mode"] == "canvas"


class TestGetDocumentInfo:
    """获取文档信息测试。"""

    @pytest.mark.asyncio
    async def test_get_info_success(self, ps: PhotoshopControl, mock_app: MagicMock) -> None:
        """成功获取文档信息。"""
        ps._app = mock_app
        ps._connected = True
        result = await ps.execute("get_document_info", {})
        assert result["name"] == "test.psd"
        assert result["width"] == 1920
        assert result["height"] == 1080
        assert result["color_mode"] == "rgb"
        assert result["layer_count"] == 4
        assert isinstance(result["layers"], list)


class TestCloseDocument:
    """关闭文档测试。"""

    @pytest.mark.asyncio
    async def test_close_without_save(self, ps: PhotoshopControl, mock_app: MagicMock) -> None:
        """不保存关闭。"""
        ps._app = mock_app
        ps._connected = True
        result = await ps.execute("close_document", {})
        assert result["status"] == "closed"
        assert result["saved"] is False

    @pytest.mark.asyncio
    async def test_close_with_save(self, ps: PhotoshopControl, mock_app: MagicMock) -> None:
        """保存并关闭。"""
        ps._app = mock_app
        ps._connected = True
        result = await ps.execute("close_document", {"save": True})
        assert result["status"] == "closed"
        assert result["saved"] is True
