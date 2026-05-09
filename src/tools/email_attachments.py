"""邮件附件处理模块。

提供邮件附件下载、发送带附件的邮件、按附件类型搜索邮件等功能。
基于 email 标准库 + imapclient + smtplib 实现，不引入额外依赖。
"""

from __future__ import annotations

import email
import os
import smtplib
from email import encoders
from email.header import decode_header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from loguru import logger


class EmailAttachmentManager:
    """邮件附件管理器。

    提供附件下载、带附件邮件发送、按附件类型搜索等功能。

    Usage::

        mgr = EmailAttachmentManager(config)
        # 下载邮件的所有附件
        result = mgr.download_attachments(message_uid=42, save_dir="/tmp/attachments")
        # 发送带附件的邮件
        result = mgr.send_email_with_attachments(
            to=["user@example.com"],
            subject="报告",
            body="请查收附件",
            attachments=["/path/to/report.pdf"],
        )
    """

    def __init__(self, config: Any) -> None:
        """初始化附件管理器。

        Args:
            config: EmailConfig 实例，包含 SMTP/IMAP 连接信息
        """
        self._config = config

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_filename(raw: str | None) -> str:
        """解码附件文件名。

        Args:
            raw: 原始文件名字符串

        Returns:
            解码后的文件名
        """
        if not raw:
            return ""
        parts = decode_header(raw)
        decoded: list[str] = []
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(part)
        return "".join(decoded)

    def _fetch_message(self, uid: int, folder: str) -> email.message.Message | None:
        """通过 IMAP 获取邮件消息对象。

        Args:
            uid: 邮件 UID
            folder: 邮箱文件夹名

        Returns:
            email.message.Message 对象，失败时返回 None
        """
        import imapclient

        server = imapclient.IMAPClient(
            self._config.imap_host, self._config.imap_port, ssl=True
        )
        try:
            server.login(self._config.address, self._config.password)
            server.select_folder(folder)
            fetched = server.fetch([uid], ["RFC822"])
            if uid not in fetched:
                return None
            raw = fetched[uid].get(b"RFC822") or b""
            if not raw:
                return None
            return email.message_from_bytes(raw)
        finally:
            server.logout()

    @staticmethod
    def _collect_attachment_parts(
        msg: email.message.Message,
    ) -> list[tuple[int, email.message.Message]]:
        """收集邮件中所有附件 part 及其索引。

        Args:
            msg: 邮件消息对象

        Returns:
            (index, part) 元组列表
        """
        attachments: list[tuple[int, email.message.Message]] = []
        idx = 0
        for part in msg.walk():
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                filename = part.get_filename()
                if filename:
                    attachments.append((idx, part))
                    idx += 1
        return attachments

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def download_attachments(
        self,
        message_uid: int,
        save_dir: str,
        folder: str = "INBOX",
    ) -> dict[str, Any]:
        """从邮件下载所有附件到指定目录。

        Args:
            message_uid: 邮件 UID
            save_dir: 保存目录路径
            folder: 邮箱文件夹名，默认 INBOX

        Returns:
            结果字典，包含下载的附件列表或错误信息
        """
        try:
            msg = self._fetch_message(message_uid, folder)
            if msg is None:
                return {"error": f"未找到邮件 UID: {message_uid}"}

            save_path = Path(save_dir)
            save_path.mkdir(parents=True, exist_ok=True)

            attachment_parts = self._collect_attachment_parts(msg)
            if not attachment_parts:
                return {
                    "downloaded": [],
                    "count": 0,
                    "message": f"邮件 UID {message_uid} 没有附件",
                }

            downloaded: list[dict[str, Any]] = []
            for idx, part in attachment_parts:
                filename = self._decode_filename(part.get_filename())
                if not filename:
                    filename = f"attachment_{idx}"

                file_path = save_path / filename
                payload = part.get_payload(decode=True)
                if payload is None:
                    logger.warning(f"附件 {filename} payload 为空，跳过")
                    continue

                file_path.write_bytes(payload)
                downloaded.append({
                    "filename": filename,
                    "path": str(file_path),
                    "size": len(payload),
                })
                logger.info(f"下载附件: {filename} ({len(payload)} bytes)")

            return {
                "downloaded": downloaded,
                "count": len(downloaded),
                "save_dir": str(save_path),
                "message_uid": message_uid,
            }
        except Exception as e:
            logger.error(f"下载附件失败: {e}")
            return {"error": f"下载附件失败: {e}"}

    def download_single_attachment(
        self,
        message_uid: int,
        attachment_index: int,
        save_path: str,
        folder: str = "INBOX",
    ) -> dict[str, Any]:
        """下载邮件中的单个指定附件。

        Args:
            message_uid: 邮件 UID
            attachment_index: 附件索引（从 0 开始）
            save_path: 保存文件路径（含文件名）
            folder: 邮箱文件夹名，默认 INBOX

        Returns:
            结果字典，包含下载的附件信息或错误信息
        """
        try:
            msg = self._fetch_message(message_uid, folder)
            if msg is None:
                return {"error": f"未找到邮件 UID: {message_uid}"}

            attachment_parts = self._collect_attachment_parts(msg)
            if not attachment_parts:
                return {"error": f"邮件 UID {message_uid} 没有附件"}

            if attachment_index < 0 or attachment_index >= len(attachment_parts):
                return {
                    "error": (
                        f"附件索引 {attachment_index} 超出范围，"
                        f"共有 {len(attachment_parts)} 个附件"
                    )
                }

            _, part = attachment_parts[attachment_index]
            filename = self._decode_filename(part.get_filename())
            payload = part.get_payload(decode=True)
            if payload is None:
                return {"error": f"附件 {filename} 内容为空"}

            target = Path(save_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

            logger.info(f"下载单个附件: {filename} -> {target} ({len(payload)} bytes)")
            return {
                "downloaded": True,
                "filename": filename,
                "path": str(target),
                "size": len(payload),
                "message_uid": message_uid,
                "attachment_index": attachment_index,
            }
        except Exception as e:
            logger.error(f"下载单个附件失败: {e}")
            return {"error": f"下载单个附件失败: {e}"}

    def send_email_with_attachments(
        self,
        to: list[str],
        subject: str,
        body: str,
        attachments: list[str],
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        html: bool = False,
    ) -> dict[str, Any]:
        """发送带附件的邮件。

        Args:
            to: 收件人地址列表
            subject: 邮件主题
            body: 邮件正文
            attachments: 附件文件路径列表
            cc: 抄送地址列表（可选）
            bcc: 密送地址列表（可选）
            html: 是否以 HTML 格式发送，默认 False

        Returns:
            发送结果字典
        """
        if not to:
            return {"error": "收件人列表不能为空"}
        if not subject:
            return {"error": "邮件主题不能为空"}
        if not attachments:
            return {"error": "附件列表不能为空，如需发送无附件邮件请使用普通发送功能"}

        try:
            # 构建邮件
            msg = MIMEMultipart()
            msg["From"] = self._config.address
            msg["To"] = ", ".join(to)
            msg["Subject"] = subject

            cc = cc or []
            bcc = bcc or []
            if cc:
                msg["Cc"] = ", ".join(cc)

            # 正文
            content_type = "html" if html else "plain"
            msg.attach(MIMEText(body, content_type, "utf-8"))

            # 附件
            attached_files: list[str] = []
            for att_path_str in attachments:
                att_path = Path(att_path_str)
                if not att_path.exists():
                    return {"error": f"附件文件不存在: {att_path}"}
                if not att_path.is_file():
                    return {"error": f"附件路径不是文件: {att_path}"}

                with open(att_path, "rb") as f:
                    file_data = f.read()

                # 根据文件扩展名推断 MIME 类型
                mime_main, mime_sub = self._guess_mime_type(att_path.name)
                part = MIMEBase(mime_main, mime_sub)
                part.set_payload(file_data)
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename*=UTF-8''{att_path.name}",
                )
                msg.attach(part)
                attached_files.append(att_path.name)
                logger.debug(f"添加附件: {att_path.name} ({len(file_data)} bytes)")

            # 发送
            all_recipients = to + cc + bcc
            if self._config.use_tls:
                server = smtplib.SMTP(self._config.smtp_host, self._config.smtp_port)
                server.ehlo()
                server.starttls()
                server.ehlo()
            else:
                server = smtplib.SMTP(self._config.smtp_host, self._config.smtp_port)

            try:
                server.login(self._config.address, self._config.password)
                server.sendmail(self._config.address, all_recipients, msg.as_string())
                logger.info(f"带附件邮件已发送: {subject} -> {all_recipients} ({len(attached_files)} 个附件)")
                return {
                    "sent": True,
                    "subject": subject,
                    "recipients": all_recipients,
                    "attachments": attached_files,
                    "attachment_count": len(attached_files),
                }
            finally:
                server.quit()

        except Exception as e:
            logger.error(f"发送带附件邮件失败: {e}")
            return {"error": f"发送失败: {e}"}

    def search_by_attachment_type(
        self,
        folder: str,
        extension: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """按附件类型搜索邮件。

        遍历指定文件夹中的邮件，查找包含指定扩展名附件的邮件。

        Args:
            folder: 邮箱文件夹名
            extension: 文件扩展名（不含点号），如 "pdf"、"docx"、"xlsx"
            limit: 返回结果上限，默认 50

        Returns:
            匹配的邮件列表
        """
        ext_lower = extension.lower().lstrip(".")
        if not ext_lower:
            return {"error": "请指定有效的文件扩展名"}

        try:
            import imapclient

            server = imapclient.IMAPClient(
                self._config.imap_host, self._config.imap_port, ssl=True
            )
            try:
                server.login(self._config.address, self._config.password)
                server.select_folder(folder)

                messages = server.search("ALL")
                if not messages:
                    return {"emails": [], "total": 0, "folder": folder, "extension": ext_lower}

                matched: list[dict[str, Any]] = []
                # 逆序处理（最新优先）
                for uid in reversed(messages):
                    if len(matched) >= limit:
                        break

                    fetched = server.fetch([uid], ["RFC822"])
                    if uid not in fetched:
                        continue
                    raw = fetched[uid].get(b"RFC822") or b""
                    if not raw:
                        continue

                    msg = email.message_from_bytes(raw)
                    attachment_found = False
                    attachment_names: list[str] = []

                    for part in msg.walk():
                        disposition = str(part.get("Content-Disposition", ""))
                        if "attachment" in disposition:
                            filename = part.get_filename()
                            if filename:
                                decoded_name = self._decode_filename(filename)
                                attachment_names.append(decoded_name)
                                if decoded_name.lower().endswith(f".{ext_lower}"):
                                    attachment_found = True

                    if attachment_found:
                        from src.tools.email_imap import build_message_summary

                        summary = build_message_summary(uid, msg)
                        summary["matching_attachments"] = [
                            n for n in attachment_names
                            if n.lower().endswith(f".{ext_lower}")
                        ]
                        summary["all_attachments"] = attachment_names
                        matched.append(summary)

                logger.info(
                    f"按附件类型搜索: .{ext_lower} 在 {folder} 中找到 {len(matched)} 封邮件"
                )
                return {
                    "emails": matched,
                    "total": len(matched),
                    "folder": folder,
                    "extension": ext_lower,
                }
            finally:
                server.logout()
        except Exception as e:
            logger.error(f"按附件类型搜索失败: {e}")
            return {"error": f"搜索失败: {e}"}

    def get_attachment_info(
        self,
        message_uid: int,
        folder: str = "INBOX",
    ) -> dict[str, Any]:
        """获取邮件的所有附件信息。

        返回附件文件名、大小、MIME 类型等信息，不下载附件内容。

        Args:
            message_uid: 邮件 UID
            folder: 邮箱文件夹名，默认 INBOX

        Returns:
            附件信息列表
        """
        try:
            msg = self._fetch_message(message_uid, folder)
            if msg is None:
                return {"error": f"未找到邮件 UID: {message_uid}"}

            attachments: list[dict[str, Any]] = []
            for part in msg.walk():
                disposition = str(part.get("Content-Disposition", ""))
                if "attachment" in disposition:
                    filename = part.get_filename()
                    if not filename:
                        continue

                    decoded_name = self._decode_filename(filename)
                    content_type = part.get_content_type()
                    payload = part.get_payload(decode=True)
                    size = len(payload) if payload else 0

                    attachments.append({
                        "index": len(attachments),
                        "filename": decoded_name,
                        "size": size,
                        "size_human": self._human_readable_size(size),
                        "content_type": content_type,
                        "extension": Path(decoded_name).suffix.lower() if decoded_name else "",
                    })

            return {
                "message_uid": message_uid,
                "folder": folder,
                "attachments": attachments,
                "count": len(attachments),
            }
        except Exception as e:
            logger.error(f"获取附件信息失败: {e}")
            return {"error": f"获取附件信息失败: {e}"}

    # ------------------------------------------------------------------
    # 静态辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _guess_mime_type(filename: str) -> tuple[str, str]:
        """根据文件扩展名推断 MIME 类型。

        Args:
            filename: 文件名

        Returns:
            (main_type, sub_type) 元组
        """
        ext = Path(filename).suffix.lower()
        mime_map: dict[str, tuple[str, str]] = {
            ".pdf": ("application", "pdf"),
            ".doc": ("application", "msword"),
            ".docx": ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ".xls": ("application", "vnd.ms-excel"),
            ".xlsx": ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ".ppt": ("application", "vnd.ms-powerpoint"),
            ".pptx": ("application", "vnd.openxmlformats-officedocument.presentationml.presentation"),
            ".zip": ("application", "zip"),
            ".rar": ("application", "x-rar-compressed"),
            ".7z": ("application", "x-7z-compressed"),
            ".tar": ("application", "x-tar"),
            ".gz": ("application", "gzip"),
            ".txt": ("text", "plain"),
            ".csv": ("text", "csv"),
            ".html": ("text", "html"),
            ".htm": ("text", "html"),
            ".json": ("application", "json"),
            ".xml": ("application", "xml"),
            ".jpg": ("image", "jpeg"),
            ".jpeg": ("image", "jpeg"),
            ".png": ("image", "png"),
            ".gif": ("image", "gif"),
            ".bmp": ("image", "bmp"),
            ".webp": ("image", "webp"),
            ".svg": ("image", "svg+xml"),
            ".mp3": ("audio", "mpeg"),
            ".wav": ("audio", "wav"),
            ".mp4": ("video", "mp4"),
            ".avi": ("video", "x-msvideo"),
            ".mkv": ("video", "x-matroska"),
        }
        return mime_map.get(ext, ("application", "octet-stream"))

    @staticmethod
    def _human_readable_size(size_bytes: int) -> str:
        """将字节数转换为人类可读的大小字符串。

        Args:
            size_bytes: 字节数

        Returns:
            可读的大小字符串，如 "1.5 MB"
        """
        if size_bytes < 0:
            return "0 B"
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024  # type: ignore[assignment]
        return f"{size_bytes:.1f} PB"
