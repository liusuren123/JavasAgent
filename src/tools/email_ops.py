"""邮件处理工具集。

提供邮件收发、搜索、管理等邮件自动化能力。
基于 smtplib (SMTP) + imapclient (IMAP) 实现。
"""

from __future__ import annotations

import asyncio
import os
import smtplib  # noqa: F401 — kept for test patch targets (src.tools.email_ops.smtplib)
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from loguru import logger

from src.tools.email_imap import (
    build_message_detail,
    build_message_summary,
    decode_header_value,
    extract_email_address,
    get_text_body,
)
from src.tools.email_send import smtp_send
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
    # 静态辅助方法（委托给 email_imap 模块，保持向后兼容）
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_header_value(value: str | None) -> str:
        return decode_header_value(value)

    @staticmethod
    def _extract_email_address(raw: str) -> tuple[str, str]:
        return extract_email_address(raw)

    @staticmethod
    def _get_text_body(msg: Any) -> str:
        return get_text_body(msg)

    def _build_message_summary(self, uid: int | str, msg: Any) -> dict[str, Any]:
        return build_message_summary(uid, msg)

    def _build_message_detail(self, uid: int | str, msg: Any) -> dict[str, Any]:
        return build_message_detail(uid, msg)

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
        """同步 SMTP 发送（在 to_thread 中执行）。委托给 email_send 模块。"""
        return smtp_send(self._config, msg, recipients)

    # ------------------------------------------------------------------
    # IMAP 操作（委托给 email_imap 模块，通过 _imap_* 实例方法保持 mock 兼容）
    # ------------------------------------------------------------------

    async def _list_emails(self, params: dict[str, Any]) -> dict[str, Any]:
        """列出收件箱邮件。"""
        cfg_err = self._require_config()
        if cfg_err:
            return cfg_err

        folder: str = params.get("folder", "INBOX")
        limit: int = min(params.get("limit", 20), 100)
        offset: int = params.get("offset", 0)
        unseen_only: bool = params.get("unseen_only", False)

        try:
            return await asyncio.to_thread(
                self._imap_list, folder, limit, offset, unseen_only
            )
        except Exception as e:
            logger.error(f"列出邮件失败: {e}")
            return {"error": f"列出邮件失败: {e}"}

    def _imap_list(self, folder: str, limit: int, offset: int, unseen_only: bool) -> dict[str, Any]:
        """同步 IMAP 列出邮件。"""
        from src.tools.email_imap import imap_list
        return imap_list(self._config, folder, limit, offset, unseen_only)

    async def _read_email(self, params: dict[str, Any]) -> dict[str, Any]:
        """读取单封邮件详情。"""
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
            return await asyncio.to_thread(
                self._imap_read, uid, folder, mark_seen
            )
        except Exception as e:
            logger.error(f"读取邮件失败: {e}")
            return {"error": f"读取邮件失败: {e}"}

    def _imap_read(self, uid: int, folder: str, mark_seen: bool) -> dict[str, Any]:
        """同步 IMAP 读取邮件详情。"""
        from src.tools.email_imap import imap_read
        return imap_read(uid, self._config, folder, mark_seen)

    async def _search_emails(self, params: dict[str, Any]) -> dict[str, Any]:
        """搜索邮件。"""
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

        if not any([query, from_addr, to_addr, since, before]):
            return {"error": "请至少提供一个搜索条件（query/from_addr/to_addr/since/before）"}

        try:
            return await asyncio.to_thread(
                self._imap_search, folder, query, from_addr, to_addr, since, before, limit
            )
        except Exception as e:
            logger.error(f"搜索邮件失败: {e}")
            return {"error": f"搜索邮件失败: {e}"}

    def _imap_search(
        self, folder: str, query: str, from_addr: str, to_addr: str,
        since: str, before: str, limit: int,
    ) -> dict[str, Any]:
        """同步 IMAP 搜索邮件。"""
        from src.tools.email_imap import imap_search
        return imap_search(self._config, folder, query, from_addr, to_addr, since, before, limit)

    async def _delete_email(self, params: dict[str, Any]) -> dict[str, Any]:
        """删除邮件。"""
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
            return await asyncio.to_thread(
                self._imap_delete, uids, folder
            )
        except Exception as e:
            logger.error(f"删除邮件失败: {e}")
            return {"error": f"删除邮件失败: {e}"}

    def _imap_delete(self, uids: list[int], folder: str) -> dict[str, Any]:
        """同步 IMAP 删除邮件。"""
        from src.tools.email_imap import imap_delete
        return imap_delete(self._config, uids, folder)

    async def _move_email(self, params: dict[str, Any]) -> dict[str, Any]:
        """移动邮件到指定文件夹。"""
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
            return await asyncio.to_thread(
                self._imap_move, uid, source_folder, dest_folder
            )
        except Exception as e:
            logger.error(f"移动邮件失败: {e}")
            return {"error": f"移动邮件失败: {e}"}

    def _imap_move(self, uid: int, source_folder: str, dest_folder: str) -> dict[str, Any]:
        """同步 IMAP 移动邮件。"""
        from src.tools.email_imap import imap_move
        return imap_move(self._config, uid, source_folder, dest_folder)

    async def _get_folders(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取邮箱文件夹列表。"""
        cfg_err = self._require_config()
        if cfg_err:
            return cfg_err

        try:
            return await asyncio.to_thread(self._imap_folders)
        except Exception as e:
            logger.error(f"获取文件夹列表失败: {e}")
            return {"error": f"获取文件夹列表失败: {e}"}

    def _imap_folders(self) -> dict[str, Any]:
        """同步 IMAP 获取文件夹列表。"""
        from src.tools.email_imap import imap_folders
        return imap_folders(self._config)


def _require_params(params: dict[str, Any], required: list[str]) -> list[str]:
    """检查必要参数是否存在。

    Args:
        params: 参数字典
        required: 必要参数名称列表

    Returns:
        缺失的参数名称列表（空列表表示全部存在）
    """
    return [k for k in required if k not in params or params[k] is None]
