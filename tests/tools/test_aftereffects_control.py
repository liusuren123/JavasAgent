"""AfterEffectsControl 测试。

使用 mock 模拟 COM 对象，验证 After Effects 控制工具的核心逻辑。
不依赖 After Effects 真正运行。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.tools.aftereffects_control import AfterEffectsControl


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def ae(tmp_path: Path) -> AfterEffectsControl:
    """创建使用临时目录的 AfterEffectsControl 实例。"""
    return AfterEffectsControl(workspace=str(tmp_path))


@pytest.fixture
def mock_app():
    """创建一个模拟的 After Effects COM 对象。"""
    app = MagicMock()

    # 项目
    project = MagicMock()
    project.Name = "TestProject"
    project.Path = "C:\\test\\test.aep"

    # 合成
    comp1 = MagicMock()
    comp1.Name = "Comp 1"
    comp1.Width = 1920
    comp1.Height = 1080
    comp1.FrameRate = 30.0
    comp1.Duration = 10.0
    comp1.BgColor = [0, 0, 0]
    comp1.PixelAspectRatio = 1.0
    comp1.TypeName = "Composition"
    comp1.Time = 0.0

    # 图层
    layer1 = MagicMock()
    layer1.Name = "Text Layer"
    layer1.Enabled = True
    layer1.Locked = False
    layer1.Solo = False
    layer1.Shy = False
    layer1.InPoint = 0.0
    layer1.OutPoint = 10.0
    layer1.Duration = 10.0
    layer1.Text = MagicMock()  # has Text → type is "text"

    layer2 = MagicMock()
    layer2.Name = "Solid Layer"
    layer2.Enabled = True
    layer2.Locked = False
    layer2.Solo = False
    layer2.Shy = False
    layer2.Source.TypeName = "Solid"
    layer2.InPoint = 0.0
    layer2.OutPoint = 5.0
    layer2.Duration = 5.0

    layers_collection = MagicMock()
    layers_collection.Count = 2
    layers_collection.__getitem__ = lambda self, idx: [layer1, layer2][idx - 1]
    comp1.Layers = layers_collection

    # 位置/缩放 mock
    pos_mock = MagicMock()
    pos_mock.Value = [960.0, 540.0]
    scale_mock = MagicMock()
    scale_mock.Value = [100.0, 100.0]
    rot_mock = MagicMock()
    rot_mock.Value = 0.0
    opacity_mock = MagicMock()
    opacity_mock.Value = 100.0

    prop_mock = MagicMock()
    prop_mock.Position = pos_mock
    prop_mock.Scale = scale_mock
    prop_mock.Rotation = rot_mock
    prop_mock.Opacity = opacity_mock

    layer1.Property = prop_mock
    layer2.Property = prop_mock

    # 项目 Items
    items = MagicMock()
    items.Count = 1
    items.__getitem__ = lambda self, idx: comp1
    project.Items = items

    # ActiveItem
    app.ActiveItem = comp1
    app.Project = project

    # Projects collection
    projects = MagicMock()
    projects.Count = 1
    projects.__getitem__ = lambda self, idx: project
    app.Projects = projects

    # RenderQueue
    rq = MagicMock()
    rq_item = MagicMock()
    output_module = MagicMock()
    rq_item.OutputModules.__getitem__ = lambda self, idx: output_module
    rq.Add.return_value = rq_item
    app.Project.RenderQueue = rq

    return app


# ======================================================================
# 连接错误处理
# ======================================================================


class TestAfterEffectsNotAvailable:
    """After Effects 不可用时的错误处理。"""

    @pytest.mark.asyncio
    async def test_not_windows(self, ae: AfterEffectsControl) -> None:
        """非 Windows 平台应返回友好错误。"""
        with patch.object(sys, "platform", "darwin"):
            result = await ae.execute("list_projects", {})
            assert "error" in result
            assert "Windows" in result["error"]

    @pytest.mark.asyncio
    async def test_pywin32_not_installed(self, ae: AfterEffectsControl) -> None:
        """pywin32 未安装时应返回安装提示。"""
        with patch.object(sys, "platform", "win32"):
            with patch.dict(sys.modules, {"win32com": None, "win32com.client": None}):
                result = await ae.execute("list_projects", {})
                assert "error" in result
                assert "pywin32" in result["error"]

    @pytest.mark.asyncio
    async def test_ae_not_running(self, ae: AfterEffectsControl) -> None:
        """After Effects 未运行时应返回连接错误。"""
        with patch.object(sys, "platform", "win32"):
            mock_win32com = MagicMock()
            mock_win32com.client.GetActiveObject.side_effect = Exception("Not found")
            with patch.dict(sys.modules, {"win32com": mock_win32com, "win32com.client": mock_win32com.client}):
                result = await ae.execute("list_projects", {})
                assert "error" in result
                assert "无法连接" in result["error"]


# ======================================================================
# Action 映射
# ======================================================================


class TestActionMapping:
    """验证所有 action 的 handler 映射。"""

    @pytest.mark.asyncio
    async def test_unknown_action(self, ae: AfterEffectsControl) -> None:
        """未知操作应返回错误和可用操作列表。"""
        result = await ae.execute("nonexistent_action", {})
        assert "error" in result
        assert "未知操作" in result["error"]
        assert "available_actions" in result

    @pytest.mark.asyncio
    async def test_all_actions_listed(self, ae: AfterEffectsControl) -> None:
        """所有 9 个操作都应出现在可用列表中。"""
        result = await ae.execute("bogus", {})
        actions = result.get("available_actions", [])
        expected = [
            "add_solid_layer", "add_text_layer", "export_frame",
            "get_active_composition", "import_file", "list_layers",
            "list_projects", "render_composition", "set_layer_property",
        ]
        assert sorted(actions) == sorted(expected)


# ======================================================================
# 路径安全
# ======================================================================


class TestPathSafety:
    """路径安全检查测试。"""

    @pytest.mark.asyncio
    async def test_render_path_traversal_blocked(self, ae: AfterEffectsControl) -> None:
        """渲染输出路径遍历应被阻止。"""
        result = await ae.execute("render_composition", {
            "output_path": "../../etc/secret.mov",
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_export_frame_path_traversal_blocked(self, ae: AfterEffectsControl) -> None:
        """导出帧路径遍历也应被阻止。"""
        result = await ae.execute("export_frame", {
            "output_path": "../../../tmp/evil.png",
        })
        assert "error" in result


# ======================================================================
# Mock COM 操作测试
# ======================================================================


class TestListProjects:
    """列出项目测试。"""

    @pytest.mark.asyncio
    async def test_list_success(self, ae: AfterEffectsControl, mock_app: MagicMock) -> None:
        """成功列出项目。"""
        ae._app = mock_app
        ae._connected = True

        result = await ae.execute("list_projects", {})
        assert result["status"] == "ok"
        assert result["project_count"] >= 1


class TestGetActiveComposition:
    """获取活动合成测试。"""

    @pytest.mark.asyncio
    async def test_get_comp_success(self, ae: AfterEffectsControl, mock_app: MagicMock) -> None:
        """成功获取合成信息。"""
        ae._app = mock_app
        ae._connected = True

        result = await ae.execute("get_active_composition", {})
        assert result["name"] == "Comp 1"
        assert result["width"] == 1920
        assert result["height"] == 1080
        assert result["fps"] == 30.0

    @pytest.mark.asyncio
    async def test_no_active_comp(self, ae: AfterEffectsControl, mock_app: MagicMock) -> None:
        """没有活动合成时应报错。"""
        mock_app.ActiveItem = None
        # Empty project items
        empty_items = MagicMock()
        empty_items.Count = 0
        mock_app.Project.Items = empty_items
        ae._app = mock_app
        ae._connected = True

        result = await ae.execute("get_active_composition", {})
        assert "error" in result


class TestListLayers:
    """列出图层测试。"""

    @pytest.mark.asyncio
    async def test_list_layers_success(self, ae: AfterEffectsControl, mock_app: MagicMock) -> None:
        """成功列出图层。"""
        ae._app = mock_app
        ae._connected = True

        result = await ae.execute("list_layers", {})
        assert result["status"] == "ok"
        assert result["layer_count"] == 2
        assert len(result["layers"]) == 2
        assert result["layers"][0]["name"] == "Text Layer"
        assert result["layers"][1]["name"] == "Solid Layer"

    @pytest.mark.asyncio
    async def test_list_layers_with_comp_name(self, ae: AfterEffectsControl, mock_app: MagicMock) -> None:
        """指定合成名称列出图层。"""
        ae._app = mock_app
        ae._connected = True

        result = await ae.execute("list_layers", {"composition_name": "Comp 1"})
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_list_layers_comp_not_found(self, ae: AfterEffectsControl, mock_app: MagicMock) -> None:
        """指定不存在的合成名应报错。"""
        ae._app = mock_app
        ae._connected = True

        result = await ae.execute("list_layers", {"composition_name": "NonExistent"})
        assert "error" in result
        assert "未找到" in result["error"]


class TestAddTextLayer:
    """添加文字图层测试。"""

    @pytest.mark.asyncio
    async def test_missing_text(self, ae: AfterEffectsControl) -> None:
        """缺少 text 参数应报错。"""
        result = await ae.execute("add_text_layer", {})
        assert "error" in result
        assert "text" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_add_text_success(self, ae: AfterEffectsControl, mock_app: MagicMock) -> None:
        """成功添加文字图层。"""
        ae._app = mock_app
        ae._connected = True

        text_layer = MagicMock()
        text_layer.Name = "Hello"
        text_layer.SourceText.Value = MagicMock()
        mock_app.ActiveItem.Layers.AddText.return_value = text_layer

        result = await ae.execute("add_text_layer", {"text": "Hello"})
        assert result["status"] == "created"
        assert result["text"] == "Hello"


class TestAddSolidLayer:
    """添加纯色图层测试。"""

    @pytest.mark.asyncio
    async def test_add_solid_success(self, ae: AfterEffectsControl, mock_app: MagicMock) -> None:
        """成功添加纯色图层。"""
        ae._app = mock_app
        ae._connected = True

        solid = MagicMock()
        solid.Name = "BG"
        mock_app.ActiveItem.Layers.AddSolid.return_value = solid

        result = await ae.execute("add_solid_layer", {
            "color": [0.5, 0.5, 0.5],
            "name": "BG",
        })
        assert result["status"] == "created"
        assert result["layer_name"] == "BG"
        assert result["color"] == [0.5, 0.5, 0.5]

    @pytest.mark.asyncio
    async def test_invalid_color(self, ae: AfterEffectsControl, mock_app: MagicMock) -> None:
        """无效颜色格式应报错。"""
        ae._app = mock_app
        ae._connected = True

        result = await ae.execute("add_solid_layer", {"color": "red"})
        assert "error" in result
        assert "颜色" in result["error"]


class TestSetLayerProperty:
    """设置图层属性测试。"""

    @pytest.mark.asyncio
    async def test_missing_layer_name(self, ae: AfterEffectsControl) -> None:
        """缺少图层名称应报错。"""
        result = await ae.execute("set_layer_property", {
            "property_name": "position",
            "value": [100, 200],
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_missing_property_name(self, ae: AfterEffectsControl) -> None:
        """缺少属性名称应报错。"""
        result = await ae.execute("set_layer_property", {
            "layer_name": "Text Layer",
            "value": [100, 200],
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_missing_value(self, ae: AfterEffectsControl) -> None:
        """缺少值应报错。"""
        result = await ae.execute("set_layer_property", {
            "layer_name": "Text Layer",
            "property_name": "position",
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_layer_not_found(self, ae: AfterEffectsControl, mock_app: MagicMock) -> None:
        """未找到图层应报错。"""
        ae._app = mock_app
        ae._connected = True

        result = await ae.execute("set_layer_property", {
            "layer_name": "NonExistent",
            "property_name": "position",
            "value": [100, 200],
        })
        assert "error" in result
        assert "未找到" in result["error"]

    @pytest.mark.asyncio
    async def test_set_position_success(self, ae: AfterEffectsControl, mock_app: MagicMock) -> None:
        """成功设置位置。"""
        ae._app = mock_app
        ae._connected = True

        result = await ae.execute("set_layer_property", {
            "layer_name": "Text Layer",
            "property_name": "position",
            "value": [100, 200],
        })
        assert result["status"] == "set"
        assert result["value"] == [100, 200]

    @pytest.mark.asyncio
    async def test_set_rotation_with_keyframe(self, ae: AfterEffectsControl, mock_app: MagicMock) -> None:
        """设置旋转带关键帧。"""
        ae._app = mock_app
        ae._connected = True

        result = await ae.execute("set_layer_property", {
            "layer_name": "Text Layer",
            "property_name": "rotation",
            "value": 45,
            "time": 2.0,
        })
        assert result["status"] == "set"
        assert result["value"] == 45


class TestRenderComposition:
    """渲染合成测试。"""

    @pytest.mark.asyncio
    async def test_missing_output_path(self, ae: AfterEffectsControl) -> None:
        """缺少输出路径应报错。"""
        result = await ae.execute("render_composition", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_unsupported_preset(self, ae: AfterEffectsControl) -> None:
        """不支持的预设应报错。"""
        result = await ae.execute("render_composition", {
            "output_path": "out.mov",
            "preset": "avi_raw",
        })
        assert "error" in result
        assert "不支持" in result["error"]

    @pytest.mark.asyncio
    async def test_render_success(self, ae: AfterEffectsControl, mock_app: MagicMock) -> None:
        """成功发起渲染。"""
        ae._app = mock_app
        ae._connected = True

        result = await ae.execute("render_composition", {
            "output_path": "output.mov",
            "preset": "h264",
        })
        assert result["status"] == "rendering"
        assert result["preset"] == "h264"


class TestImportFile:
    """导入文件测试。"""

    @pytest.mark.asyncio
    async def test_missing_path(self, ae: AfterEffectsControl) -> None:
        """缺少路径应报错。"""
        result = await ae.execute("import_file", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_file_not_found(self, ae: AfterEffectsControl) -> None:
        """文件不存在应报错。"""
        result = await ae.execute("import_file", {"path": "nonexistent.mp4"})
        assert "error" in result
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_import_success(self, ae: AfterEffectsControl, mock_app: MagicMock, tmp_path: Path) -> None:
        """成功导入文件。"""
        test_file = tmp_path / "footage.mp4"
        test_file.write_bytes(b"fake video content")

        imported_item = MagicMock()
        imported_item.Name = "footage.mp4"
        mock_app.Project.ImportFile.return_value = imported_item

        ae._app = mock_app
        ae._connected = True

        result = await ae.execute("import_file", {"path": "footage.mp4"})
        assert result["status"] == "imported"
        assert result["name"] == "footage.mp4"


class TestExportFrame:
    """导出帧测试。"""

    @pytest.mark.asyncio
    async def test_missing_output_path(self, ae: AfterEffectsControl) -> None:
        """缺少输出路径应报错。"""
        result = await ae.execute("export_frame", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_unsupported_format(self, ae: AfterEffectsControl) -> None:
        """不支持的格式应报错。"""
        result = await ae.execute("export_frame", {"output_path": "out.gif"})
        assert "error" in result
        assert "不支持" in result["error"]

    @pytest.mark.asyncio
    async def test_export_frame_success(self, ae: AfterEffectsControl, mock_app: MagicMock) -> None:
        """成功导出帧。"""
        ae._app = mock_app
        ae._connected = True

        result = await ae.execute("export_frame", {"output_path": "frame.png"})
        assert result["status"] == "exported"
        assert result["format"] == ".png"
