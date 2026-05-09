"""EmailAttachmentManager 邮件附件处理测试。"""

from __future__ import annotations

import email
import sys
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# 确保 imapclient 模块可以被 mock（测试环境可能未安装 imapclient）
if "imapclient" not in sys.modules:
    sys.modules["imapclient"] = MagicMock()

from src.tools.email_attachments import EmailAttachmentManager
from src.tools.email_ops import EmailConfig


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def config() -> EmailConfig:
    """创建测试用的邮件配置。"""
    return EmailConfig({
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "imap_host": "imap.example.com",
        "imap_port": 993,
        "address": "test@example.com",
        "password": "test-password",
        "use_tls": True,
    })


@pytest.fixture
def manager(config: EmailConfig) -> EmailAttachmentManager:
    """创建附件管理器实例。"""
    return EmailAttachmentManager(config)


def _make_email_with_attachments(
    subject: str = "Test Email",
    filenames_and_content: list[tuple[str, bytes]] | None = None,
) -> email.message.Message:
    """构建带附件的测试邮件。

    Args:
        subject: 邮件主题
        filenames_and_content: (文件名, 内容) 元组列表

    Returns:
        email.message.Message 对象
    """
    msg = MIMEMultipart()
    msg["From"] = "sender@example.com"
    msg["To"] = "test@example.com"
    msg["Subject"] = subject
    msg.attach(MIMEText("这是测试正文", "plain", "utf-8"))

    if filenames_and_content:
        for filename, content in filenames_and_content:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(content)
            from email import encoders
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            )
            msg.attach(part)

    return msg


def _make_email_without_attachments() -> email.message.Message:
    """构建不带附件的测试邮件。"""
    msg = MIMEMultipart()
    msg["From"] = "sender@example.com"
    msg["To"] = "test@example.com"
    msg["Subject"] = "No Attachments"
    msg.attach(MIMEText("纯文本邮件", "plain", "utf-8"))
    return msg


def _mock_imap_fetch(msg: email.message.Message) -> MagicMock:
    """创建模拟的 IMAP fetch 结果。

    Args:
        msg: 要返回的邮件消息

    Returns:
        配置好的 MagicMock 对象
    """
    mock_server = MagicMock()
    mock_server.login.return_value = None
    mock_server.select_folder.return_value = None
    mock_server.logout.return_value = None

    raw_bytes = msg.as_bytes()
    uid = 42
    mock_server.fetch.return_value = {uid: {b"RFC822": raw_bytes}}

    return mock_server


# ======================================================================
# download_attachments
# ======================================================================


class TestDownloadAttachments:
    """下载所有附件测试。"""

    def test_download_multiple_attachments(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """下载多附件邮件的所有附件。"""
        msg = _make_email_with_attachments("Test", [
            ("report.pdf", b"PDF content here"),
            ("data.xlsx", b"Excel content here"),
        ])
        mock_server = _mock_imap_fetch(msg)

        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.download_attachments(42, str(tmp_path / "downloads"))

        assert result["count"] == 2
        assert result["message_uid"] == 42
        assert len(result["downloaded"]) == 2
        filenames = [a["filename"] for a in result["downloaded"]]
        assert "report.pdf" in filenames
        assert "data.xlsx" in filenames
        # 验证文件实际存在
        for a in result["downloaded"]:
            assert Path(a["path"]).exists()

    def test_download_no_attachments(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """没有附件的邮件应返回空列表。"""
        msg = _make_email_without_attachments()
        mock_server = _mock_imap_fetch(msg)

        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.download_attachments(42, str(tmp_path / "downloads"))

        assert result["count"] == 0
        assert result["downloaded"] == []

    def test_download_email_not_found(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """邮件不存在时返回错误。"""
        mock_server = MagicMock()
        mock_server.login.return_value = None
        mock_server.select_folder.return_value = None
        mock_server.logout.return_value = None
        mock_server.fetch.return_value = {}  # 空结果

        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.download_attachments(999, str(tmp_path))

        assert "error" in result
        assert "999" in result["error"]

    def test_download_creates_directory(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """下载时自动创建不存在的目录。"""
        msg = _make_email_with_attachments("Test", [("file.txt", b"content")])
        mock_server = _mock_imap_fetch(msg)

        new_dir = str(tmp_path / "new" / "subdir")
        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.download_attachments(42, new_dir)

        assert result["count"] == 1
        assert Path(new_dir).exists()

    def test_download_imap_error(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """IMAP 连接异常时的错误处理。"""
        with patch("imapclient.IMAPClient", side_effect=Exception("Connection refused")):
            result = manager.download_attachments(42, str(tmp_path))

        assert "error" in result


# ======================================================================
# download_single_attachment
# ======================================================================


class TestDownloadSingleAttachment:
    """下载单个附件测试。"""

    def test_download_first_attachment(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """下载第一个附件。"""
        msg = _make_email_with_attachments("Test", [
            ("first.pdf", b"PDF data"),
            ("second.docx", b"DOCX data"),
        ])
        mock_server = _mock_imap_fetch(msg)

        save_path = str(tmp_path / "first.pdf")
        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.download_single_attachment(42, 0, save_path)

        assert result["downloaded"] is True
        assert result["filename"] == "first.pdf"
        assert result["size"] == 8
        assert Path(save_path).exists()

    def test_download_second_attachment(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """下载第二个附件。"""
        msg = _make_email_with_attachments("Test", [
            ("first.pdf", b"PDF data"),
            ("second.docx", b"DOCX data"),
        ])
        mock_server = _mock_imap_fetch(msg)

        save_path = str(tmp_path / "second.docx")
        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.download_single_attachment(42, 1, save_path)

        assert result["downloaded"] is True
        assert result["filename"] == "second.docx"

    def test_download_invalid_index(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """无效的附件索引应返回错误。"""
        msg = _make_email_with_attachments("Test", [("file.txt", b"data")])
        mock_server = _mock_imap_fetch(msg)

        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.download_single_attachment(42, 5, str(tmp_path / "file.txt"))

        assert "error" in result
        assert "超出范围" in result["error"]

    def test_download_negative_index(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """负索引应返回错误。"""
        msg = _make_email_with_attachments("Test", [("file.txt", b"data")])
        mock_server = _mock_imap_fetch(msg)

        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.download_single_attachment(42, -1, str(tmp_path / "file.txt"))

        assert "error" in result

    def test_download_no_attachments(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """没有附件时返回错误。"""
        msg = _make_email_without_attachments()
        mock_server = _mock_imap_fetch(msg)

        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.download_single_attachment(42, 0, str(tmp_path / "file.txt"))

        assert "error" in result
        assert "没有附件" in result["error"]


# ======================================================================
# send_email_with_attachments
# ======================================================================


class TestSendEmailWithAttachments:
    """发送带附件邮件测试。"""

    def test_send_with_one_attachment(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """发送带一个附件的邮件。"""
        # 创建测试附件文件
        att_file = tmp_path / "report.pdf"
        att_file.write_bytes(b"PDF content")

        mock_smtp = MagicMock()
        mock_smtp.ehlo.return_value = None
        mock_smtp.starttls.return_value = None
        mock_smtp.login.return_value = None
        mock_smtp.sendmail.return_value = {}
        mock_smtp.quit.return_value = None

        with patch("src.tools.email_attachments.smtplib.SMTP", return_value=mock_smtp):
            result = manager.send_email_with_attachments(
                to=["user@example.com"],
                subject="报告",
                body="请查收",
                attachments=[str(att_file)],
            )

        assert result["sent"] is True
        assert result["attachment_count"] == 1
        assert "report.pdf" in result["attachments"]

    def test_send_with_multiple_attachments(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """发送带多个附件的邮件。"""
        files = []
        for name, content in [("a.pdf", b"PDF"), ("b.xlsx", b"XLSX"), ("c.docx", b"DOCX")]:
            f = tmp_path / name
            f.write_bytes(content)
            files.append(str(f))

        mock_smtp = MagicMock()
        mock_smtp.ehlo.return_value = None
        mock_smtp.starttls.return_value = None
        mock_smtp.login.return_value = None
        mock_smtp.sendmail.return_value = {}
        mock_smtp.quit.return_value = None

        with patch("src.tools.email_attachments.smtplib.SMTP", return_value=mock_smtp):
            result = manager.send_email_with_attachments(
                to=["user@example.com"],
                subject="多附件",
                body="见附件",
                attachments=files,
            )

        assert result["sent"] is True
        assert result["attachment_count"] == 3

    def test_send_empty_to(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """空收件人列表应返回错误。"""
        result = manager.send_email_with_attachments(
            to=[],
            subject="test",
            body="body",
            attachments=["/some/file.pdf"],
        )
        assert "error" in result
        assert "收件人" in result["error"]

    def test_send_empty_subject(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """空主题应返回错误。"""
        result = manager.send_email_with_attachments(
            to=["a@b.com"],
            subject="",
            body="body",
            attachments=["/some/file.pdf"],
        )
        assert "error" in result
        assert "主题" in result["error"]

    def test_send_no_attachments(self, manager: EmailAttachmentManager) -> None:
        """空附件列表应返回错误。"""
        result = manager.send_email_with_attachments(
            to=["a@b.com"],
            subject="test",
            body="body",
            attachments=[],
        )
        assert "error" in result
        assert "附件" in result["error"]

    def test_send_nonexistent_attachment(self, manager: EmailAttachmentManager) -> None:
        """附件文件不存在应返回错误。"""
        result = manager.send_email_with_attachments(
            to=["a@b.com"],
            subject="test",
            body="body",
            attachments=["/nonexistent/file.pdf"],
        )
        assert "error" in result
        assert "不存在" in result["error"]

    def test_send_with_cc_bcc(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """发送带抄送和密送的邮件。"""
        att_file = tmp_path / "file.txt"
        att_file.write_bytes(b"data")

        mock_smtp = MagicMock()
        mock_smtp.ehlo.return_value = None
        mock_smtp.starttls.return_value = None
        mock_smtp.login.return_value = None
        mock_smtp.sendmail.return_value = {}
        mock_smtp.quit.return_value = None

        with patch("src.tools.email_attachments.smtplib.SMTP", return_value=mock_smtp):
            result = manager.send_email_with_attachments(
                to=["to@example.com"],
                subject="CC/BCC test",
                body="body",
                attachments=[str(att_file)],
                cc=["cc@example.com"],
                bcc=["bcc@example.com"],
            )

        assert result["sent"] is True
        assert "cc@example.com" in result["recipients"]
        assert "bcc@example.com" in result["recipients"]

    def test_send_smtp_error(self, manager: EmailAttachmentManager, tmp_path: Path) -> None:
        """SMTP 连接失败时的错误处理。"""
        att_file = tmp_path / "file.txt"
        att_file.write_bytes(b"data")

        with patch("src.tools.email_attachments.smtplib.SMTP", side_effect=Exception("SMTP refused")):
            result = manager.send_email_with_attachments(
                to=["a@b.com"],
                subject="test",
                body="body",
                attachments=[str(att_file)],
            )

        assert "error" in result


# ======================================================================
# search_by_attachment_type
# ======================================================================


class TestSearchByAttachmentType:
    """按附件类型搜索测试。"""

    def test_search_pdf_attachments(self, manager: EmailAttachmentManager) -> None:
        """搜索包含 PDF 附件的邮件。"""
        msg_with_pdf = _make_email_with_attachments("PDF Report", [
            ("report.pdf", b"PDF content"),
            ("notes.txt", b"text"),
        ])
        msg_without_pdf = _make_email_with_attachments("Other", [
            ("data.xlsx", b"Excel"),
        ])

        pdf_bytes = msg_with_pdf.as_bytes()
        other_bytes = msg_without_pdf.as_bytes()

        mock_server = MagicMock()
        mock_server.login.return_value = None
        mock_server.select_folder.return_value = None
        mock_server.logout.return_value = None
        mock_server.search.return_value = [1, 2]
        mock_server.fetch.side_effect = [
            {2: {b"RFC822": other_bytes}},  # uid=2 (reversed first)
            {1: {b"RFC822": pdf_bytes}},    # uid=1 (reversed second)
        ]

        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.search_by_attachment_type("INBOX", "pdf")

        assert result["total"] == 1
        assert result["emails"][0]["subject"] == "PDF Report"
        assert "report.pdf" in result["emails"][0]["matching_attachments"]

    def test_search_no_results(self, manager: EmailAttachmentManager) -> None:
        """搜索没有匹配结果。"""
        msg = _make_email_with_attachments("Doc Only", [
            ("report.docx", b"Word content"),
        ])

        mock_server = MagicMock()
        mock_server.login.return_value = None
        mock_server.select_folder.return_value = None
        mock_server.logout.return_value = None
        mock_server.search.return_value = [1]
        mock_server.fetch.return_value = {1: {b"RFC822": msg.as_bytes()}}

        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.search_by_attachment_type("INBOX", "pdf")

        assert result["total"] == 0
        assert result["emails"] == []

    def test_search_empty_folder(self, manager: EmailAttachmentManager) -> None:
        """空文件夹搜索。"""
        mock_server = MagicMock()
        mock_server.login.return_value = None
        mock_server.select_folder.return_value = None
        mock_server.logout.return_value = None
        mock_server.search.return_value = []

        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.search_by_attachment_type("INBOX", "pdf")

        assert result["total"] == 0

    def test_search_empty_extension(self, manager: EmailAttachmentManager) -> None:
        """空扩展名应返回错误。"""
        result = manager.search_by_attachment_type("INBOX", "")
        assert "error" in result

    def test_search_extension_with_dot(self, manager: EmailAttachmentManager) -> None:
        """扩展名带点号时应正确处理。"""
        msg = _make_email_with_attachments("PDF", [("file.pdf", b"data")])
        mock_server = MagicMock()
        mock_server.login.return_value = None
        mock_server.select_folder.return_value = None
        mock_server.logout.return_value = None
        mock_server.search.return_value = [1]
        mock_server.fetch.return_value = {1: {b"RFC822": msg.as_bytes()}}

        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.search_by_attachment_type("INBOX", ".pdf")

        assert result["total"] == 1

    def test_search_respects_limit(self, manager: EmailAttachmentManager) -> None:
        """搜索结果受 limit 限制。"""
        messages_data = {}
        for i in range(5):
            msg = _make_email_with_attachments(f"Email {i}", [(f"file{i}.pdf", b"data")])
            messages_data[i + 1] = {b"RFC822": msg.as_bytes()}

        mock_server = MagicMock()
        mock_server.login.return_value = None
        mock_server.select_folder.return_value = None
        mock_server.logout.return_value = None
        mock_server.search.return_value = list(range(1, 6))

        def mock_fetch(uids, fields):
            return {uid: messages_data[uid] for uid in uids if uid in messages_data}

        mock_server.fetch.side_effect = mock_fetch

        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.search_by_attachment_type("INBOX", "pdf", limit=2)

        assert result["total"] == 2


# ======================================================================
# get_attachment_info
# ======================================================================


class TestGetAttachmentInfo:
    """获取附件信息测试。"""

    def test_get_info_with_attachments(self, manager: EmailAttachmentManager) -> None:
        """获取包含附件的邮件附件信息。"""
        msg = _make_email_with_attachments("Test", [
            ("report.pdf", b"PDF content here"),
            ("data.xlsx", b"Excel content here"),
        ])
        mock_server = _mock_imap_fetch(msg)

        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.get_attachment_info(42)

        assert result["count"] == 2
        assert result["message_uid"] == 42

        # 验证第一个附件信息
        att0 = result["attachments"][0]
        assert att0["filename"] == "report.pdf"
        assert att0["size"] == 16  # len(b"PDF content here")
        assert att0["extension"] == ".pdf"
        assert att0["content_type"] == "application/octet-stream"

        # 验证第二个附件信息
        att1 = result["attachments"][1]
        assert att1["filename"] == "data.xlsx"
        assert att1["size"] == 18  # len(b"Excel content here")
        assert att1["extension"] == ".xlsx"

    def test_get_info_no_attachments(self, manager: EmailAttachmentManager) -> None:
        """没有附件时返回空列表。"""
        msg = _make_email_without_attachments()
        mock_server = _mock_imap_fetch(msg)

        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.get_attachment_info(42)

        assert result["count"] == 0
        assert result["attachments"] == []

    def test_get_info_email_not_found(self, manager: EmailAttachmentManager) -> None:
        """邮件不存在时返回错误。"""
        mock_server = MagicMock()
        mock_server.login.return_value = None
        mock_server.select_folder.return_value = None
        mock_server.logout.return_value = None
        mock_server.fetch.return_value = {}

        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.get_attachment_info(999)

        assert "error" in result
        assert "999" in result["error"]

    def test_get_info_custom_folder(self, manager: EmailAttachmentManager) -> None:
        """指定文件夹获取附件信息。"""
        msg = _make_email_with_attachments("Test", [("file.txt", b"data")])
        mock_server = _mock_imap_fetch(msg)

        with patch("imapclient.IMAPClient", return_value=mock_server) as mock_cls:
            result = manager.get_attachment_info(42, folder="Sent")

        assert result["count"] == 1
        assert result["folder"] == "Sent"

    def test_get_info_size_human(self, manager: EmailAttachmentManager) -> None:
        """验证 size_human 字段格式。"""
        msg = _make_email_with_attachments("Test", [
            ("small.txt", b"x" * 100),
            ("medium.pdf", b"x" * 2048),
        ])
        mock_server = _mock_imap_fetch(msg)

        with patch("imapclient.IMAPClient", return_value=mock_server):
            result = manager.get_attachment_info(42)

        assert "B" in result["attachments"][0]["size_human"]
        assert "KB" in result["attachments"][1]["size_human"]

    def test_get_info_imap_error(self, manager: EmailAttachmentManager) -> None:
        """IMAP 连接异常时的错误处理。"""
        with patch("imapclient.IMAPClient", side_effect=Exception("Timeout")):
            result = manager.get_attachment_info(42)

        assert "error" in result


# ======================================================================
# 静态辅助方法
# ======================================================================


class TestStaticHelpers:
    """静态辅助方法测试。"""

    def test_guess_mime_type_common(self) -> None:
        """常见文件类型 MIME 推断。"""
        assert EmailAttachmentManager._guess_mime_type("file.pdf") == ("application", "pdf")
        assert EmailAttachmentManager._guess_mime_type("file.docx") == (
            "application",
            "vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert EmailAttachmentManager._guess_mime_type("file.xlsx") == (
            "application",
            "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        assert EmailAttachmentManager._guess_mime_type("file.png") == ("image", "png")
        assert EmailAttachmentManager._guess_mime_type("file.jpg") == ("image", "jpeg")
        assert EmailAttachmentManager._guess_mime_type("file.mp4") == ("video", "mp4")

    def test_guess_mime_type_unknown(self) -> None:
        """未知文件类型回退到 octet-stream。"""
        assert EmailAttachmentManager._guess_mime_type("file.xyz123") == (
            "application",
            "octet-stream",
        )

    def test_human_readable_size(self) -> None:
        """文件大小格式化测试。"""
        assert EmailAttachmentManager._human_readable_size(0) == "0.0 B"
        assert "B" in EmailAttachmentManager._human_readable_size(100)
        assert "KB" in EmailAttachmentManager._human_readable_size(2048)
        assert "MB" in EmailAttachmentManager._human_readable_size(2 * 1024 * 1024)
        assert "GB" in EmailAttachmentManager._human_readable_size(3 * 1024 * 1024 * 1024)

    def test_human_readable_size_negative(self) -> None:
        """负数大小返回 0 B。"""
        assert EmailAttachmentManager._human_readable_size(-1) == "0 B"

    def test_decode_filename_ascii(self) -> None:
        """ASCII 文件名解码。"""
        assert EmailAttachmentManager._decode_filename("report.pdf") == "report.pdf"

    def test_decode_filename_none(self) -> None:
        """None 文件名返回空字符串。"""
        assert EmailAttachmentManager._decode_filename(None) == ""

    def test_decode_filename_encoded(self) -> None:
        """编码文件名解码。"""
        result = EmailAttachmentManager._decode_filename("=?utf-8?b?5rWL6K+V5paH5pys?=.pdf")
        assert result.endswith(".pdf")
