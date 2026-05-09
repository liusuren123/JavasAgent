"""邮件处理工具集。

提供邮件收发、搜索、管理等邮件自动化能力。
基于 smtplib (SMTP) + imapclient (IMAP) 实现。
"""

from __future__ import annotations

import asyncio
import email
import os
import smtplib
from email.header import decode_header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr
from pathlib import Path
from typing import Any

from loguru import logger

from src.utils.path_safety import PathSafetyError, safe_resolve_path


class EmailConfig:
    """邮件配置，从环境变量或配置文件加载。

    优先级：环境变量 > 配置文件值 > 默认值。
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        cfg = cfg or {}
        self.smtp_host: str = cfg.get("smtp_host", "")
        self.smtp_port: int = int(cfg.get("smtp_port", 587))
        self.imap_host: str = cfg.get("imap_host", "")
        self.imap_port: int = int(cfg.get("imap_port", 993))
        self.address: str = cfg.get("address", "")
        self.password: str = os.environ.get(
            "JAVAS_EMAIL_PASSWORD", cfg.get("password", "")
        )
        self.use_tls: bool = cfg.get("use_tls", True)

    @property
    def is_configured(self) -> bool:
        """检查邮件配置是否完整。"""
        return bool(
            self.smtp_host
            and self.imap_host
            and self.address
            and self.password
        )


class EmailOps:
    """邮件处理工具集。

    支持邮件收发、搜索、文件夹管理等操作。

    Usage::

        email_ops = EmailOps(workspace="/path/to/workspace")
        # 发送邮件
        result = await email_ops.execute("send_email", {
            "to": ["user@example.com"],
            "subject": "测试邮件",
            "body": "这是一封测试邮件",
        })
        # 列出收件箱
        result = await email_ops.execute("list_emails", {"limit": 10})
    """

    def __init__(self, workspace: str | None = None, config: dict[str, Any] | None = None) -> None:
        self._workspace = Path(workspace) if workspace else Path.cwd()
        self._config = EmailConfig(config)

    async def execute(self, action: str, params: dict[str, Any]) -> Any:
        """执行邮件操作。

        Args:
            action: 操作类型
            params: 操作参数

        Returns:
            操作结果字典
        """
        handlers: dict[str, Any] = {
            "send_email": self._send_email,
            "list_emails": self._list_emails,
            "read_email": self._read_email,
            "search_emails": self._search_emails,
            "delete_email": self._delete_email,
            "move_email": self._move_email,
            "get_folders": self._get_folders,
        }

        handler = handlers.get(action)
        if handler is None:
            logger.error(f"未知邮件操作: {action}")
            return {
                "error": f"未知操作: {action}",
                "available_actions": sorted(handlers.keys()),
            }

        return await handler(params)

    def _require_config(self) -> dict[str, str] | None:
        """检查配置是否就绪，未就绪时返回 error dict。"""
        if not self._config.is_configured:
            return {
                "error": (
                    "邮件服务未配置。请在 config/default.yaml 中填写 email 配置，"
                    "或设置环境变量 JAVAS_EMAIL_PASSWORD。"
                )
            }
        return None

    def _safe_path(self, user_path: str) -> Path:
        """安全解析附件路径。"""
        return safe_resolve_path(self._workspace, user_path)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_header_value(value: str | None) -> str:
        """解码邮件头部字段（Subject / From / To 等）。

        Args:
            value: 原始头部值

        Returns:
            解码后的可读字符串
        """
        if not value:
            return ""
        parts = decode_header(value)
        decoded: list[str] = []
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(part)
        return "".join(decoded)

    @staticmethod
    def _extract_email_address(raw: str) -> tuple[str, str]:
        """从邮件地址字段提取显示名和地址。

        Args:
            raw: 原始地址字符串，如 ``"张三 <zhangsan@example.com>"``

        Returns:
            (display_name, email_address) 元组
        """
        display, addr = parseaddr(raw)
        return display or "", addr or raw

    @staticmethod
    def _get_text_body(msg: email.message.Message) -> str:
        """从邮件消息中提取纯文本正文。

        优先取 text/plain，回退到 text/html（去除标签）。

        Args:
            msg: email.message.Message 对象

        Returns:
            正文纯文本
        """
        text_body = ""
        html_body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))
                if "attachment" in disposition:
                    continue
                try:
                    payload = part.get_payload(decode=True)
                    if payload is None:
                        continue
                    charset = part.get_content_charset() or "utf-8"
                    text = payload.decode(charset, errors="replace")
                except Exception:
                    continue
                if content_type == "text/plain":
                    text_body = text
                elif content_type == "text/html" and not text_body:
                    html_body = text
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    text_body = payload.decode(charset, errors="replace")
            except Exception:
                pass

        if text_body:
            return text_body.strip()
        if html_body:
            # 简单去除 HTML 标签
            import re
            return re.sub(r"<[^>]+>", "", html_body).strip()
        return ""

    def _build_message_summary(self, uid: int | str, msg: email.message.Message) -> dict[str, Any]:
        """将邮件消息构建为摘要字典。

        Args:
            uid: 邮件 UID
            msg: email.message.Message 对象

        Returns:
            摘要字典
        """
        subject = self._decode_header_value(msg.get("Subject", ""))
        from_raw = self._decode_header_value(msg.get("From", ""))
        from_name, from_addr = self._extract_email_address(from_raw)
        to_raw = self._decode_header_value(msg.get("To", ""))
        date_str = msg.get("Date", "")

        return {
            "uid": uid,
            "subject": subject,
            "from": from_addr,
            "from_name": from_name,
            "to": to_raw,
            "date": date_str,
            "flags": [],
        }

    def _build_message_detail(self, uid: int | str, msg: email.message.Message) -> dict[str, Any]:
        """将邮件消息构建为详情字典（含正文）。

        Args:
            uid: 邮件 UID
            msg: email.message.Message 对象

        Returns:
            详情字典
        """
        summary = self._build_message_summary(uid, msg)
        summary["body"] = self._get_text_body(msg)

        # 附件列表
        attachments: list[str] = []
        if msg.is_multipart():
            for part in msg.walk():
                disposition = str(part.get("Content-Disposition", ""))
                if "attachment" in disposition:
                    filename = part.get_filename()
                    if filename:
                        attachments.append(self._decode_header_value(filename))
        summary["attachments"] = attachments

        return summary

    # ------------------------------------------------------------------
    # SMTP 发送
    # ------------------------------------------------------------------

    async def _send_email(self, params: dict[str, Any]) -> dict[str, Any]:
        """发送邮件。

        Params:
            to: 收件人地址列表（必填）
            subject: 邮件主题（必填）
            body: 邮件正文（必填）
            cc: 抄送地址列表（可选）
            bcc: 密送地址列表（可选）
            html: 是否以 HTML 格式发送（默认 False）
            attachments: 附件路径列表（可选，相对于 workspace）
            reply_to: 回复地址（可选）
        """
        missing = _require_params(params, ["to", "subject", "body"])
        if missing:
            return {"error": f"缺少必要参数: {', '.join(missing)}"}

        cfg_err = self._require_config()
        if cfg_err:
            return cfg_err

        to_addrs: list[str] = params["to"]
        if isinstance(to_addrs, str):
            to_addrs = [to_addrs]
        subject: str = params["subject"]
        body: str = params["body"]
        cc: list[str] = params.get("cc", [])
        bcc: list[str] = params.get("bcc", [])
        html: bool = params.get("html", False)
        attachment_paths: list[str] = params.get("attachments", [])
        reply_to: str | None = params.get("reply_to")

        # 构建邮件
        msg = MIMEMultipart()
        msg["From"] = self._config.address
        msg["To"] = ", ".join(to_addrs)
        msg["Subject"] = subject

        if cc:
            msg["Cc"] = ", ".join(cc)
        if reply_to:
            msg["Reply-To"] = reply_to

        # 正文
        content_type = "html" if html else "plain"
        msg.attach(MIMEText(body, content_type, "utf-8"))

        # 附件
        for att_path_str in attachment_paths:
            try:
                att_path = self._safe_path(att_path_str)
            except PathSafetyError as e:
                return {"error": f"附件路径不安全: {e}"}

            if not att_path.exists():
                return {"error": f"附件文件不存在: {att_path}"}

            try:
                with open(att_path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                from email import encoders
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename*=UTF-8''{att_path.name}",
                )
                msg.attach(part)
            except Exception as e:
                logger.error(f"读取附件失败: {att_path} - {e}")
                return {"error": f"读取附件失败: {e}"}

        # 发送
        all_recipients = to_addrs + cc + bcc
        try:
            result = await asyncio.to_thread(
                self._smtp_send, msg, all_recipients
            )
            return result
        except Exception as e:
            logger.error(f"发送邮件失败: {e}")
            return {"error": f"发送失败: {e}"}

    def _smtp_send(self, msg: MIMEMultipart, recipients: list[str]) -> dict[str, Any]:
        """同步 SMTP 发送（在 to_thread 中执行）。

        Args:
            msg: 构建好的邮件消息
            recipients: 所有收件人列表

        Returns:
            发送结果字典
        """
        cfg = self._config
        if cfg.use_tls:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port)

        try:
            server.login(cfg.address, cfg.password)
            server.sendmail(cfg.address, recipients, msg.as_string())
            logger.info(f"邮件已发送: {msg['Subject']} -> {recipients}")
            return {
                "sent": True,
                "subject": msg["Subject"],
                "recipients": recipients,
            }
        finally:
            server.quit()

    # ------------------------------------------------------------------
    # IMAP 读取
    # ------------------------------------------------------------------

    async def _list_emails(self, params: dict[str, Any]) -> dict[str, Any]:
        """列出收件箱邮件。

        Params:
            folder: 文件夹名称（默认 "INBOX"）
            limit: 返回邮件数量（默认 20，最大 100）
            offset: 偏移量（默认 0）
            unseen_only: 是否只显示未读邮件（默认 False）
        """
        cfg_err = self._require_config()
        if cfg_err:
            return cfg_err

        folder: str = params.get("folder", "INBOX")
        limit: int = min(params.get("limit", 20), 100)
        offset: int = params.get("offset", 0)
        unseen_only: bool = params.get("unseen_only", False)

        try:
            result = await asyncio.to_thread(
                self._imap_list, folder, limit, offset, unseen_only
            )
            return result
        except Exception as e:
            logger.error(f"列出邮件失败: {e}")
            return {"error": f"列出邮件失败: {e}"}

    def _imap_list(
        self, folder: str, limit: int, offset: int, unseen_only: bool
    ) -> dict[str, Any]:
        """同步 IMAP 列出邮件（在 to_thread 中执行）。"""
        import imapclient

        cfg = self._config
        server = imapclient.IMAPClient(cfg.imap_host, cfg.imap_port, ssl=True)
        try:
            server.login(cfg.address, cfg.password)
            server.select_folder(folder)

            # 搜索条件
            criteria = "UNSEEN" if unseen_only else "ALL"
            messages = server.search(criteria)

            if not messages:
                return {"emails": [], "total": 0, "folder": folder}

            total = len(messages)
            # 倒序取最新的，应用 offset 和 limit
            reversed_uids = list(reversed(messages))
            selected = reversed_uids[offset : offset + limit]

            # 批量获取摘要信息
            fetched = server.fetch(selected, ["ENVELOPE", "FLAGS", "RFC822.HEADER"])
            emails: list[dict[str, Any]] = []
            for uid in selected:
                if uid not in fetched:
                    continue
                data = fetched[uid]
                raw_headers = data.get(b"RFC822.HEADER", b"")
                if raw_headers:
                    msg = email.message_from_bytes(raw_headers)
                    summary = self._build_message_summary(uid, msg)
                    flags = data.get(b"FLAGS", [])
                    summary["flags"] = [f.decode() if isinstance(f, bytes) else str(f) for f in flags]
                    emails.append(summary)

            logger.info(f"列出邮件: {folder} ({len(emails)}/{total})")
            return {
                "emails": emails,
                "total": total,
                "folder": folder,
                "limit": limit,
                "offset": offset,
            }
        finally:
            server.logout()

    async def _read_email(self, params: dict[str, Any]) -> dict[str, Any]:
        """读取单封邮件详情。

        Params:
            uid: 邮件 UID（必填）
            folder: 文件夹名称（默认 "INBOX"）
            mark_seen: 是否标记为已读（默认 True）
        """
        missing = _require_params(params, ["uid"])
        if missing:
            return {"error": f"缺少必要参数: {', '.join(missing)}"}

        cfg_err = self._require_config()
        if cfg_err:
            return cfg_err

        uid: int = int(params["uid"])
        folder: str = params.get("folder", "INBOX")
        mark_seen: bool = params.get("mark_seen", True)

        try:
            result = await asyncio.to_thread(
                self._imap_read, uid, folder, mark_seen
            )
            return result
        except Exception as e:
            logger.error(f"读取邮件失败: {e}")
            return {"error": f"读取邮件失败: {e}"}

    def _imap_read(self, uid: int, folder: str, mark_seen: bool) -> dict[str, Any]:
        """同步 IMAP 读取邮件详情（在 to_thread 中执行）。"""
        import imapclient

        cfg = self._config
        server = imapclient.IMAPClient(cfg.imap_host, cfg.imap_port, ssl=True)
        try:
            server.login(cfg.address, cfg.password)
            server.select_folder(folder)

            fetch_flags = b"RFC822" if mark_seen else b"BODY.PEEK[]"
            fetched = server.fetch([uid], [fetch_flags])
            if uid not in fetched:
                return {"error": f"未找到邮件 UID: {uid}"}

            data = fetched[uid]
            raw = data.get(b"RFC822") or data.get(b"BODY[]") or b""
            if not raw:
                return {"error": f"邮件内容为空: UID {uid}"}

            msg = email.message_from_bytes(raw)
            detail = self._build_message_detail(uid, msg)

            logger.info(f"读取邮件: UID {uid} - {detail['subject']}")
            return detail
        finally:
            server.logout()

    async def _search_emails(self, params: dict[str, Any]) -> dict[str, Any]:
        """搜索邮件。

        Params:
            query: 关键词（匹配主题和正文）
            from_addr: 发件人地址过滤
            to_addr: 收件人地址过滤
            since: 起始日期（YYYY-MM-DD）
            before: 结束日期（YYYY-MM-DD）
            folder: 文件夹名称（默认 "INBOX"）
            limit: 返回邮件数量（默认 20，最大 100）
        """
        cfg_err = self._require_config()
        if cfg_err:
            return cfg_err

        query: str = params.get("query", "")
        from_addr: str = params.get("from_addr", "")
        to_addr: str = params.get("to_addr", "")
        since: str = params.get("since", "")
        before: str = params.get("before", "")
        folder: str = params.get("folder", "INBOX")
        limit: int = min(params.get("limit", 20), 100)

        # 至少要有一个搜索条件
        if not any([query, from_addr, to_addr, since, before]):
            return {"error": "请至少提供一个搜索条件（query/from_addr/to_addr/since/before）"}

        try:
            result = await asyncio.to_thread(
                self._imap_search, folder, query, from_addr, to_addr, since, before, limit
            )
            return result
        except Exception as e:
            logger.error(f"搜索邮件失败: {e}")
            return {"error": f"搜索邮件失败: {e}"}

    def _imap_search(
        self,
        folder: str,
        query: str,
        from_addr: str,
        to_addr: str,
        since: str,
        before: str,
        limit: int,
    ) -> dict[str, Any]:
        """同步 IMAP 搜索邮件（在 to_thread 中执行）。"""
        import imapclient

        cfg = self._config
        server = imapclient.IMAPClient(cfg.imap_host, cfg.imap_port, ssl=True)
        try:
            server.login(cfg.address, cfg.password)
            server.select_folder(folder)

            # 构建 IMAP 搜索条件
            criteria: list[str | bytes] = []
            if query:
                criteria.extend(["TEXT", query])
            if from_addr:
                criteria.extend(["FROM", from_addr])
            if to_addr:
                criteria.extend(["TO", to_addr])
            if since:
                criteria.extend(["SINCE", since])
            if before:
                criteria.extend(["BEFORE", before])

            messages = server.search(criteria) if criteria else server.search("ALL")

            if not messages:
                return {"emails": [], "total": 0, "folder": folder}

            total = len(messages)
            reversed_uids = list(reversed(messages))[:limit]

            fetched = server.fetch(reversed_uids, ["ENVELOPE", "RFC822.HEADER"])
            emails: list[dict[str, Any]] = []
            for uid in reversed_uids:
                if uid not in fetched:
                    continue
                data = fetched[uid]
                raw_headers = data.get(b"RFC822.HEADER", b"")
                if raw_headers:
                    msg = email.message_from_bytes(raw_headers)
                    emails.append(self._build_message_summary(uid, msg))

            logger.info(f"搜索邮件: {folder} ({len(emails)}/{total})")
            return {
                "emails": emails,
                "total": total,
                "folder": folder,
            }
        finally:
            server.logout()

    async def _delete_email(self, params: dict[str, Any]) -> dict[str, Any]:
        """删除邮件。

        Params:
            uid: 邮件 UID（必填，可以是单个或列表）
            folder: 文件夹名称（默认 "INBOX"）
        """
        missing = _require_params(params, ["uid"])
        if missing:
            return {"error": f"缺少必要参数: {', '.join(missing)}"}

        cfg_err = self._require_config()
        if cfg_err:
            return cfg_err

        uid_raw = params["uid"]
        uids: list[int] = uid_raw if isinstance(uid_raw, list) else [int(uid_raw)]
        folder: str = params.get("folder", "INBOX")

        try:
            result = await asyncio.to_thread(
                self._imap_delete, uids, folder
            )
            return result
        except Exception as e:
            logger.error(f"删除邮件失败: {e}")
            return {"error": f"删除邮件失败: {e}"}

    def _imap_delete(self, uids: list[int], folder: str) -> dict[str, Any]:
        """同步 IMAP 删除邮件（在 to_thread 中执行）。"""
        import imapclient

        cfg = self._config
        server = imapclient.IMAPClient(cfg.imap_host, cfg.imap_port, ssl=True)
        try:
            server.login(cfg.address, cfg.password)
            server.select_folder(folder)

            server.set_flags(uids, [b"\\Deleted"])
            server.expunge()

            logger.info(f"删除邮件: UID {uids} (文件夹: {folder})")
            return {
                "deleted": True,
                "uids": uids,
                "folder": folder,
            }
        finally:
            server.logout()

    async def _move_email(self, params: dict[str, Any]) -> dict[str, Any]:
        """移动邮件到指定文件夹。

        Params:
            uid: 邮件 UID（必填）
            dest_folder: 目标文件夹名称（必填）
            source_folder: 源文件夹名称（默认 "INBOX"）
        """
        missing = _require_params(params, ["uid", "dest_folder"])
        if missing:
            return {"error": f"缺少必要参数: {', '.join(missing)}"}

        cfg_err = self._require_config()
        if cfg_err:
            return cfg_err

        uid: int = int(params["uid"])
        dest_folder: str = params["dest_folder"]
        source_folder: str = params.get("source_folder", "INBOX")

        try:
            result = await asyncio.to_thread(
                self._imap_move, uid, source_folder, dest_folder
            )
            return result
        except Exception as e:
            logger.error(f"移动邮件失败: {e}")
            return {"error": f"移动邮件失败: {e}"}

    def _imap_move(self, uid: int, source_folder: str, dest_folder: str) -> dict[str, Any]:
        """同步 IMAP 移动邮件（在 to_thread 中执行）。"""
        import imapclient

        cfg = self._config
        server = imapclient.IMAPClient(cfg.imap_host, cfg.imap_port, ssl=True)
        try:
            server.login(cfg.address, cfg.password)
            server.select_folder(source_folder)

            server.move([uid], dest_folder)

            logger.info(f"移动邮件: UID {uid} ({source_folder} -> {dest_folder})")
            return {
                "moved": True,
                "uid": uid,
                "source_folder": source_folder,
                "dest_folder": dest_folder,
            }
        finally:
            server.logout()

    async def _get_folders(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取邮箱文件夹列表。

        Params:
            （无必填参数）
        """
        cfg_err = self._require_config()
        if cfg_err:
            return cfg_err

        try:
            result = await asyncio.to_thread(self._imap_folders)
            return result
        except Exception as e:
            logger.error(f"获取文件夹列表失败: {e}")
            return {"error": f"获取文件夹列表失败: {e}"}

    def _imap_folders(self) -> dict[str, Any]:
        """同步 IMAP 获取文件夹列表（在 to_thread 中执行）。"""
        import imapclient

        cfg = self._config
        server = imapclient.IMAPClient(cfg.imap_host, cfg.imap_port, ssl=True)
        try:
            server.login(cfg.address, cfg.password)

            folders = server.list_folders()
            folder_list: list[dict[str, Any]] = []
            for flags, delimiter, name in folders:
                folder_list.append({
                    "name": name,
                    "delimiter": delimiter,
                    "flags": [f.decode() if isinstance(f, bytes) else str(f) for f in flags],
                })

            logger.info(f"获取文件夹列表: {len(folder_list)} 个")
            return {
                "folders": folder_list,
                "count": len(folder_list),
            }
        finally:
            server.logout()


def _require_params(params: dict[str, Any], required: list[str]) -> list[str]:
    """检查必要参数是否存在。

    Args:
        params: 参数字典
        required: 必要参数名称列表

    Returns:
        缺失的参数名称列表（空列表表示全部存在）
    """
    return [k for k in required if k not in params or params[k] is None]
