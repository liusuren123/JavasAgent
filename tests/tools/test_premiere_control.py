"""PremiereControl 测试。

使用 mock 模拟 COM 对象，验证 Premiere 控制工具的核心逻辑。
不依赖 Premiere 真正运行。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.tools.premiere_control import PremiereControl


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def pr(tmp_path: Path) -> PremiereControl:
    """创建使用临时目录的 PremiereControl 实例。"""
    return PremiereControl(workspace=str(tmp_path))


@pytest.fixture
def mock_app():
    """创建一个模拟的 Premiere Pro COM 对象。"""
    app = MagicMock()

    # 项目
    project = MagicMock()
    project.Name = "test_project"
    project.Path = "C:\\Projects\\test_project.prproj"

    # 序列
    seq1 = MagicMock()
    seq1.Name = "Sequence 01"
    seq1.SequenceID = "seq_001"
    seq1.Duration = 60.0
    seq1.End = 60.0

    seq_settings = MagicMock()
    seq_settings.VideoWidth = 1920
    seq_settings.VideoHeight = 1080
    seq_settings.VideoFrameRate = 29.97
    seq_settings.AudioSampleRate = 48000
    seq1.Settings = seq_settings

    video_tracks = MagicMock()
    video_tracks.Count = 3
    audio_tracks = MagicMock()
    audio_tracks.Count = 2
    seq1.VideoTracks = video_tracks
    seq1.AudioTracks = audio_tracks

    sequences = MagicMock()
    sequences.Count = 1
    sequences.__getitem__ = MagicMock(return_value=seq1)
    sequences.__iter__ = MagicMock(return_value=iter([seq1]))
    project.Sequences = sequences

    # 素材
    media1 = MagicMock()
    media1.Name = "clip1.mp4"
    media1.MediaType = "Movie"
    media2 = MagicMock()
    media2.Name = "clip2.mov"
    media2.MediaType = "Movie"

    media_items = MagicMock()
    media_items.Count = 2
    media_items.__getitem__ = MagicMock(side_effect=lambda i: [media1, media2][i])
    media_items.__iter__ = MagicMock(return_value=iter([media1, media2]))
    project.MediaItems = media_items

    # ProjectManager
    pm = MagicMock()
    pm.CurrentProject = project
    pm.ActiveSequence = seq1
    app.ProjectManager = pm

    return app


# ======================================================================
# 连接错误处理
# ======================================================================


class TestPremiereNotAvailable:
    """Premiere 不可用时的错误处理。"""

    @pytest.mark.asyncio
    async def test_not_windows(self, pr: PremiereControl) -> None:
        """非 Windows 平台应返回友好错误。"""
        with patch.object(sys, "platform", "darwin"):
            result = await pr.execute("open_project", {"path": "test.prproj"})
            assert "error" in result
            assert "Windows" in result["error"]

    @pytest.mark.asyncio
    async def test_pywin32_not_installed(self, pr: PremiereControl) -> None:
        """pywin32 未安装时应返回安装提示。"""
        with patch.object(sys, "platform", "win32"):
            with patch.dict(sys.modules, {"win32com": None, "win32com.client": None}):
                result = await pr.execute("open_project", {"path": "test.prproj"})
                assert "error" in result
                assert "pywin32" in result["error"]

    @pytest.mark.asyncio
    async def test_premiere_not_running(self, pr: PremiereControl, tmp_path: Path) -> None:
        """Premiere 未运行时应返回连接错误。"""
        with patch.object(sys, "platform", "win32"):
            test_file = tmp_path / "test.prproj"
            test_file.write_bytes(b"fake")
            mock_win32com = MagicMock()
            mock_win32com.client.GetActiveObject.side_effect = Exception("Not found")
            with patch.dict(sys.modules, {"win32com": mock_win32com, "win32com.client": mock_win32com.client}):
                result = await pr.execute("open_project", {"path": "test.prproj"})
                assert "error" in result
                assert "无法连接" in result["error"] or "Premiere" in result["error"]


# ======================================================================
# Action 映射
# ======================================================================


class TestActionMapping:
    """验证 action handler 映射。"""

    @pytest.mark.asyncio
    async def test_unknown_action(self, pr: PremiereControl) -> None:
        """未知操作应返回错误和可用操作列表。"""
        result = await pr.execute("nonexistent_action", {})
        assert "error" in result
        assert "未知操作" in result["error"]
        assert "available_actions" in result

    @pytest.mark.asyncio
    async def test_all_actions_listed(self, pr: PremiereControl) -> None:
        """所有 6 个操作都应出现在可用列表中。"""
        result = await pr.execute("bogus", {})
        actions = result.get("available_actions", [])
        expected = [
            "add_clip_to_timeline", "export_video", "get_project_info",
            "get_sequence_info", "import_media", "open_project",
        ]
        assert sorted(actions) == sorted(expected)


# ======================================================================
# 参数验证
# ======================================================================


class TestParamValidation:
    """各 action 的参数验证。"""

    @pytest.mark.asyncio
    async def test_open_project_missing_path(self, pr: PremiereControl) -> None:
        """open_project 缺少 path 参数应报错。"""
        result = await pr.execute("open_project", {})
        assert "error" in result
        assert "path" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_open_project_wrong_extension(self, pr: PremiereControl, mock_app: MagicMock, tmp_path: Path) -> None:
        """open_project 非 .prproj 文件应报错。"""
        wrong_file = tmp_path / "test.txt"
        wrong_file.write_text("not a project")
        pr._app = mock_app
        pr._connected = True
        result = await pr.execute("open_project", {"path": "test.txt"})
        assert "error" in result
        assert ".prproj" in result["error"]

    @pytest.mark.asyncio
    async def test_import_media_missing_paths(self, pr: PremiereControl) -> None:
        """import_media 缺少 paths 参数应报错。"""
        result = await pr.execute("import_media", {})
        assert "error" in result
        assert "paths" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_import_media_too_many_files(self, pr: PremiereControl) -> None:
        """import_media 超过 50 个文件应报错。"""
        paths = [f"clip{i}.mp4" for i in range(51)]
        result = await pr.execute("import_media", {"paths": paths})
        assert "error" in result
        assert "50" in result["error"]

    @pytest.mark.asyncio
    async def test_add_clip_missing_media_name(self, pr: PremiereControl) -> None:
        """add_clip_to_timeline 缺少 media_name 应报错。"""
        result = await pr.execute("add_clip_to_timeline", {})
        assert "error" in result
        assert "media_name" in result["error"]

    @pytest.mark.asyncio
    async def test_add_clip_negative_track(self, pr: PremiereControl) -> None:
        """add_clip_to_timeline 负轨道索引应报错。"""
        result = await pr.execute("add_clip_to_timeline", {
            "media_name": "test.mp4", "track_index": -1,
        })
        assert "error" in result
        assert "负数" in result["error"]

    @pytest.mark.asyncio
    async def test_add_clip_negative_offset(self, pr: PremiereControl) -> None:
        """add_clip_to_timeline 负时间偏移应报错。"""
        result = await pr.execute("add_clip_to_timeline", {
            "media_name": "test.mp4", "time_offset": -5.0,
        })
        assert "error" in result
        assert "负数" in result["error"]

    @pytest.mark.asyncio
    async def test_export_video_missing_output_path(self, pr: PremiereControl) -> None:
        """export_video 缺少 output_path 应报错。"""
        result = await pr.execute("export_video", {})
        assert "error" in result
        assert "output_path" in result["error"]

    @pytest.mark.asyncio
    async def test_export_video_unsupported_preset(self, pr: PremiereControl) -> None:
        """export_video 不支持的预设应报错。"""
        result = await pr.execute("export_video", {"output_path": "out.mp4", "preset": "webm"})
        assert "error" in result
        assert "不支持" in result["error"]
        assert "available_presets" in result


# ======================================================================
# 路径安全
# ======================================================================


class TestPathSafety:
    """路径安全检查。"""

    @pytest.mark.asyncio
    async def test_path_traversal_blocked_open(self, pr: PremiereControl) -> None:
        """open_project 路径遍历应被阻止。"""
        result = await pr.execute("open_project", {"path": "../../etc/secret.prproj"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_path_traversal_blocked_export(self, pr: PremiereControl) -> None:
        """export_video 路径遍历应被阻止。"""
        result = await pr.execute("export_video", {"output_path": "../../tmp/evil.mp4"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_path_traversal_blocked_import(self, pr: PremiereControl) -> None:
        """import_media 路径遍历应被阻止。"""
        result = await pr.execute("import_media", {"paths": ["../../etc/secret.mp4"]})
        assert "error" in result


# ======================================================================
# Mock COM 操作测试
# ======================================================================


class TestOpenProject:
    """打开项目测试。"""

    @pytest.mark.asyncio
    async def test_open_nonexistent_file(self, pr: PremiereControl) -> None:
        """文件不存在应报错。"""
        result = await pr.execute("open_project", {"path": "nonexistent.prproj"})
        assert "error" in result
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_open_success(self, pr: PremiereControl, mock_app: MagicMock, tmp_path: Path) -> None:
        """成功打开项目。"""
        proj_file = tmp_path / "test.prproj"
        proj_file.write_bytes(b"fake premiere project")
        mock_project = MagicMock()
        mock_project.Name = "test_project"
        mock_app.OpenProject.return_value = mock_project

        pr._app = mock_app
        pr._connected = True

        result = await pr.execute("open_project", {"path": "test.prproj"})
        assert result["status"] == "opened"
        assert result["project_name"] == "test_project"
        mock_app.OpenProject.assert_called_once()


class TestGetProjectInfo:
    """获取项目信息测试。"""

    @pytest.mark.asyncio
    async def test_no_project(self, pr: PremiereControl, mock_app: MagicMock) -> None:
        """没有打开的项目应报错。"""
        mock_app.ProjectManager.CurrentProject = None
        pr._app = mock_app
        pr._connected = True
        result = await pr.execute("get_project_info", {})
        assert "error" in result
        assert "没有打开" in result["error"]

    @pytest.mark.asyncio
    async def test_get_info_success(self, pr: PremiereControl, mock_app: MagicMock) -> None:
        """成功获取项目信息。"""
        pr._app = mock_app
        pr._connected = True
        result = await pr.execute("get_project_info", {})
        assert result["name"] == "test_project"
        assert isinstance(result["sequences"], list)
        assert result["media_count"] == 2


class TestImportMedia:
    """导入媒体测试。"""

    @pytest.mark.asyncio
    async def test_import_nonexistent(self, pr: PremiereControl, mock_app: MagicMock) -> None:
        """导入不存在的文件应报错。"""
        pr._app = mock_app
        pr._connected = True
        result = await pr.execute("import_media", {"paths": ["ghost.mp4"]})
        assert "error" in result
        assert "没有找到" in result["error"]

    @pytest.mark.asyncio
    async def test_import_success(self, pr: PremiereControl, mock_app: MagicMock, tmp_path: Path) -> None:
        """成功导入媒体。"""
        media_file = tmp_path / "clip1.mp4"
        media_file.write_bytes(b"fake video")

        mock_app.ProjectManager.CurrentProject.ImportMedia.return_value = MagicMock()
        pr._app = mock_app
        pr._connected = True

        result = await pr.execute("import_media", {"paths": ["clip1.mp4"]})
        assert result["status"] == "imported"
        assert result["imported_count"] == 1


class TestAddClipToTimeline:
    """添加素材到时间线测试。"""

    @pytest.mark.asyncio
    async def test_media_not_found(self, pr: PremiereControl, mock_app: MagicMock) -> None:
        """素材不存在应报错。"""
        pr._app = mock_app
        pr._connected = True
        result = await pr.execute("add_clip_to_timeline", {"media_name": "nonexistent.mp4"})
        assert "error" in result
        assert "未找到素材" in result["error"]

    @pytest.mark.asyncio
    async def test_add_clip_success(self, pr: PremiereControl, mock_app: MagicMock) -> None:
        """成功添加素材到时间线。"""
        pr._app = mock_app
        pr._connected = True
        result = await pr.execute("add_clip_to_timeline", {"media_name": "clip1.mp4"})
        assert result["status"] == "clip_added"
        assert result["media_name"] == "clip1.mp4"
        assert result["track_index"] == 0
        assert result["time_offset"] == 0.0


class TestExportVideo:
    """导出视频测试。"""

    @pytest.mark.asyncio
    async def test_export_success(self, pr: PremiereControl, mock_app: MagicMock) -> None:
        """成功开始导出。"""
        pr._app = mock_app
        pr._connected = True
        result = await pr.execute("export_video", {"output_path": "output.mp4", "preset": "h264"})
        assert result["status"] == "exporting"
        assert "output_path" in result
        assert result["preset"] == "h264"


class TestGetSequenceInfo:
    """获取序列信息测试。"""

    @pytest.mark.asyncio
    async def test_no_project(self, pr: PremiereControl, mock_app: MagicMock) -> None:
        """没有项目应报错。"""
        mock_app.ProjectManager.CurrentProject = None
        pr._app = mock_app
        pr._connected = True
        result = await pr.execute("get_sequence_info", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_info_success(self, pr: PremiereControl, mock_app: MagicMock) -> None:
        """成功获取序列信息。"""
        pr._app = mock_app
        pr._connected = True
        result = await pr.execute("get_sequence_info", {})
        assert result["name"] == "Sequence 01"
        assert result["width"] == 1920
        assert result["height"] == 1080
        assert result["video_track_count"] == 3
        assert result["audio_track_count"] == 2

    @pytest.mark.asyncio
    async def test_get_info_named_sequence(self, pr: PremiereControl, mock_app: MagicMock) -> None:
        """按名称获取指定序列。"""
        pr._app = mock_app
        pr._connected = True
        result = await pr.execute("get_sequence_info", {"sequence_name": "Sequence 01"})
        assert result["name"] == "Sequence 01"

    @pytest.mark.asyncio
    async def test_get_info_missing_sequence_name(self, pr: PremiereControl, mock_app: MagicMock) -> None:
        """不存在的序列名称应报错。"""
        pr._app = mock_app
        pr._connected = True
        result = await pr.execute("get_sequence_info", {"sequence_name": "NonExistent"})
        assert "error" in result
        assert "未找到序列" in result["error"]
