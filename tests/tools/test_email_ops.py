"""EmailOps 工具测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.tools.email_ops import EmailConfig, EmailOps


# ======================================================================
# 辅助
# ======================================================================


@pytest.fixture
def email_ops(tmp_path: Path) -> EmailOps:
    """创建使用临时目录作为 workspace 的 EmailOps 实例。"""
    return EmailOps(workspace=str(tmp_path))


@pytest.fixture
def configured_email_ops(tmp_path: Path) -> EmailOps:
    """创建已配置邮件服务的 EmailOps 实例。"""
    config = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "imap_host": "imap.example.com",
        "imap_port": 993,
        "address": "test@example.com",
        "password": "test-password",
        "use_tls": True,
    }
    return EmailOps(workspace=str(tmp_path), config=config)


# ======================================================================
# 初始化 & 配置
# ======================================================================


class TestEmailOpsInit:
    """初始化和配置相关测试。"""

    def test_default_init(self) -> None:
        ops = EmailOps()
        assert ops._config is not None
        assert not ops._config.is_configured

    def test_init_with_workspace(self, tmp_path: Path) -> None:
        ops = EmailOps(workspace=str(tmp_path))
        assert ops._workspace == tmp_path

    def test_init_with_config(self) -> None:
        config = {
            "smtp_host": "smtp.test.com",
            "imap_host": "imap.test.com",
            "address": "a@b.com",
            "password": "secret",
        }
        ops = EmailOps(config=config)
        assert ops._config.is_configured

    def test_config_env_override(self) -> None:
        """环境变量 JAVAS_EMAIL_PASSWORD 覆盖配置文件密码。"""
        config = {"smtp_host": "s", "imap_host": "i", "address": "a@b.com", "password": "file-pw"}
        with patch.dict("os.environ", {"JAVAS_EMAIL_PASSWORD": "env-pw"}):
            ops = EmailOps(config=config)
            assert ops._config.password == "env-pw"

    def test_config_missing_fields(self) -> None:
        """缺少关键字段时 is_configured 为 False。"""
        ops = EmailOps(config={"smtp_host": "smtp.test.com"})
        assert not ops._config.is_configured


# ======================================================================
# 通用 / 错误处理
# ======================================================================


class TestEmailOpsCommon:
    """通用功能和错误处理测试。"""

    @pytest.mark.asyncio
    async def test_unknown_action(self, email_ops: EmailOps) -> None:
        result = await email_ops.execute("nonexistent", {})
        assert "error" in result
        assert "available_actions" in result
        assert isinstance(result["available_actions"], list)
        # 验证所有预期的 action 都在列表中
        for action in ["send_email", "list_emails", "read_email", "search_emails",
                        "delete_email", "move_email", "get_folders"]:
            assert action in result["available_actions"]

    @pytest.mark.asyncio
    async def test_unconfigured_action_returns_error(self, email_ops: EmailOps) -> None:
        """未配置邮件服务时，执行操作应返回错误。"""
        result = await email_ops.execute("send_email", {
            "to": ["a@b.com"],
            "subject": "test",
            "body": "hello",
        })
        assert "error" in result
        assert "未配置" in result["error"]


# ======================================================================
# send_email 参数验证
# ======================================================================


class TestSendEmail:
    """发送邮件参数验证测试。"""

    @pytest.mark.asyncio
    async def test_send_missing_to(self, configured_email_ops: EmailOps) -> None:
        result = await configured_email_ops.execute("send_email", {
            "subject": "test",
            "body": "hello",
        })
        assert "error" in result
        assert "to" in result["error"]

    @pytest.mark.asyncio
    async def test_send_missing_subject(self, configured_email_ops: EmailOps) -> None:
        result = await configured_email_ops.execute("send_email", {
            "to": ["a@b.com"],
            "body": "hello",
        })
        assert "error" in result
        assert "subject" in result["error"]

    @pytest.mark.asyncio
    async def test_send_missing_body(self, configured_email_ops: EmailOps) -> None:
        result = await configured_email_ops.execute("send_email", {
            "to": ["a@b.com"],
            "subject": "test",
        })
        assert "error" in result
        assert "body" in result["error"]

    @pytest.mark.asyncio
    async def test_send_with_mock_smtp(self, configured_email_ops: EmailOps) -> None:
        """使用 mock SMTP 发送邮件。"""
        mock_smtp = MagicMock()
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)

        with patch("src.tools.email_ops.smtplib.SMTP", return_value=mock_smtp):
            result = await configured_email_ops.execute("send_email", {
                "to": ["recipient@example.com"],
                "subject": "测试邮件",
                "body": "这是测试内容",
            })

        assert result.get("sent") is True
        assert "测试邮件" in result["subject"]
        assert "recipient@example.com" in result["recipients"]

    @pytest.mark.asyncio
    async def test_send_with_attachment_path_traversal(self, configured_email_ops: EmailOps) -> None:
        """附件路径遍历应被阻止。"""
        result = await configured_email_ops.execute("send_email", {
            "to": ["a@b.com"],
            "subject": "test",
            "body": "hello",
            "attachments": ["../../etc/passwd"],
        })
        assert "error" in result


# ======================================================================
# list_emails 参数验证 & mock
# ======================================================================


class TestListEmails:
    """列出邮件测试。"""

    @pytest.mark.asyncio
    async def test_list_with_mock_imap(self, configured_email_ops: EmailOps) -> None:
        """使用 mock 返回值验证 list_emails 接口完整性。"""
        mock_result = {
            "emails": [
                {"uid": 1, "subject": "Test1", "from": "a@b.com", "date": "Mon, 1 Jan 2024"},
                {"uid": 2, "subject": "Test2", "from": "c@d.com", "date": "Tue, 2 Jan 2024"},
            ],
            "total": 2,
            "folder": "INBOX",
            "limit": 20,
            "offset": 0,
        }
        with patch.object(configured_email_ops, "_imap_list", return_value=mock_result):
            result = await configured_email_ops.execute("list_emails", {})
            assert result["total"] == 2
            assert len(result["emails"]) == 2
            assert result["emails"][0]["subject"] == "Test1"

    @pytest.mark.asyncio
    async def test_list_default_params(self, configured_email_ops: EmailOps) -> None:
        """验证默认参数正常传递。"""
        with patch.object(configured_email_ops, "_imap_list", return_value={"emails": [], "total": 0, "folder": "INBOX"}) as mock:
            result = await configured_email_ops.execute("list_emails", {})
            mock.assert_called_once_with("INBOX", 20, 0, False)
            assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_list_custom_params(self, configured_email_ops: EmailOps) -> None:
        """自定义参数传递。"""
        with patch.object(configured_email_ops, "_imap_list", return_value={"emails": [], "total": 0, "folder": "Sent"}) as mock:
            result = await configured_email_ops.execute("list_emails", {
                "folder": "Sent",
                "limit": 5,
                "offset": 10,
                "unseen_only": True,
            })
            mock.assert_called_once_with("Sent", 5, 10, True)


# ======================================================================
# read_email 参数验证
# ======================================================================


class TestReadEmail:
    """读取邮件测试。"""

    @pytest.mark.asyncio
    async def test_read_missing_uid(self, configured_email_ops: EmailOps) -> None:
        result = await configured_email_ops.execute("read_email", {})
        assert "error" in result
        assert "uid" in result["error"]

    @pytest.mark.asyncio
    async def test_read_with_mock(self, configured_email_ops: EmailOps) -> None:
        with patch.object(
            configured_email_ops, "_imap_read",
            return_value={"uid": 42, "subject": "Hello", "body": "World", "from": "a@b.com", "attachments": []}
        ) as mock:
            result = await configured_email_ops.execute("read_email", {"uid": 42})
            mock.assert_called_once_with(42, "INBOX", True)
            assert result["subject"] == "Hello"


# ======================================================================
# search_emails 参数验证
# ======================================================================


class TestSearchEmails:
    """搜索邮件测试。"""

    @pytest.mark.asyncio
    async def test_search_no_criteria(self, configured_email_ops: EmailOps) -> None:
        """没有任何搜索条件应返回错误。"""
        result = await configured_email_ops.execute("search_emails", {})
        assert "error" in result
        assert "搜索条件" in result["error"]

    @pytest.mark.asyncio
    async def test_search_with_query(self, configured_email_ops: EmailOps) -> None:
        with patch.object(
            configured_email_ops, "_imap_search",
            return_value={"emails": [], "total": 0, "folder": "INBOX"}
        ) as mock:
            result = await configured_email_ops.execute("search_emails", {"query": "测试"})
            assert result["total"] == 0


# ======================================================================
# delete_email 参数验证
# ======================================================================


class TestDeleteEmail:
    """删除邮件测试。"""

    @pytest.mark.asyncio
    async def test_delete_missing_uid(self, configured_email_ops: EmailOps) -> None:
        result = await configured_email_ops.execute("delete_email", {})
        assert "error" in result
        assert "uid" in result["error"]

    @pytest.mark.asyncio
    async def test_delete_with_mock(self, configured_email_ops: EmailOps) -> None:
        with patch.object(
            configured_email_ops, "_imap_delete",
            return_value={"deleted": True, "uids": [42], "folder": "INBOX"}
        ) as mock:
            result = await configured_email_ops.execute("delete_email", {"uid": 42})
            mock.assert_called_once_with([42], "INBOX")
            assert result["deleted"] is True

    @pytest.mark.asyncio
    async def test_delete_multiple_uids(self, configured_email_ops: EmailOps) -> None:
        with patch.object(
            configured_email_ops, "_imap_delete",
            return_value={"deleted": True, "uids": [1, 2, 3], "folder": "INBOX"}
        ) as mock:
            result = await configured_email_ops.execute("delete_email", {"uid": [1, 2, 3]})
            mock.assert_called_once_with([1, 2, 3], "INBOX")


# ======================================================================
# move_email 参数验证
# ======================================================================


class TestMoveEmail:
    """移动邮件测试。"""

    @pytest.mark.asyncio
    async def test_move_missing_uid(self, configured_email_ops: EmailOps) -> None:
        result = await configured_email_ops.execute("move_email", {"dest_folder": "Archive"})
        assert "error" in result
        assert "uid" in result["error"]

    @pytest.mark.asyncio
    async def test_move_missing_dest_folder(self, configured_email_ops: EmailOps) -> None:
        result = await configured_email_ops.execute("move_email", {"uid": 42})
        assert "error" in result
        assert "dest_folder" in result["error"]

    @pytest.mark.asyncio
    async def test_move_with_mock(self, configured_email_ops: EmailOps) -> None:
        with patch.object(
            configured_email_ops, "_imap_move",
            return_value={"moved": True, "uid": 42, "source_folder": "INBOX", "dest_folder": "Archive"}
        ) as mock:
            result = await configured_email_ops.execute("move_email", {
                "uid": 42,
                "dest_folder": "Archive",
            })
            mock.assert_called_once_with(42, "INBOX", "Archive")
            assert result["moved"] is True


# ======================================================================
# get_folders 参数验证
# ======================================================================


class TestGetFolders:
    """获取文件夹列表测试。"""

    @pytest.mark.asyncio
    async def test_get_folders_with_mock(self, configured_email_ops: EmailOps) -> None:
        with patch.object(
            configured_email_ops, "_imap_folders",
            return_value={"folders": [{"name": "INBOX", "delimiter": "/", "flags": []}], "count": 1}
        ) as mock:
            result = await configured_email_ops.execute("get_folders", {})
            assert result["count"] == 1
            assert result["folders"][0]["name"] == "INBOX"


# ======================================================================
# 配置缺失降级
# ======================================================================


class TestConfigDegradation:
    """配置缺失时的优雅降级测试。"""

    @pytest.mark.asyncio
    async def test_send_without_config(self, email_ops: EmailOps) -> None:
        result = await email_ops.execute("send_email", {
            "to": ["a@b.com"],
            "subject": "test",
            "body": "hello",
        })
        assert "error" in result
        assert "未配置" in result["error"]

    @pytest.mark.asyncio
    async def test_list_without_config(self, email_ops: EmailOps) -> None:
        result = await email_ops.execute("list_emails", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_read_without_config(self, email_ops: EmailOps) -> None:
        result = await email_ops.execute("read_email", {"uid": 1})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_search_without_config(self, email_ops: EmailOps) -> None:
        result = await email_ops.execute("search_emails", {"query": "test"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_delete_without_config(self, email_ops: EmailOps) -> None:
        result = await email_ops.execute("delete_email", {"uid": 1})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_move_without_config(self, email_ops: EmailOps) -> None:
        result = await email_ops.execute("move_email", {"uid": 1, "dest_folder": "Archive"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_folders_without_config(self, email_ops: EmailOps) -> None:
        result = await email_ops.execute("get_folders", {})
        assert "error" in result
