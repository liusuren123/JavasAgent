"""邮件 IMAP 操作模块。

提供邮件列表、读取、搜索、删除、移动、文件夹管理等功能。
包含 IMAP 相关的辅助函数。
"""

from __future__ import annotations

import email
import re
from email.header import decode_header
from email.utils import parseaddr
from typing import Any

from loguru import logger


# ======================================================================
# 辅助函数
# ======================================================================


def decode_header_value(value: str | None) -> str:
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


def extract_email_address(raw: str) -> tuple[str, str]:
    """从邮件地址字段提取显示名和地址。

    Args:
        raw: 原始地址字符串，如 ``"张三 <zhangsan@example.com>"``

    Returns:
        (display_name, email_address) 元组
    """
    display, addr = parseaddr(raw)
    return display or "", addr or raw


def get_text_body(msg: email.message.Message) -> str:
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
        return re.sub(r"<[^>]+>", "", html_body).strip()
    return ""


def build_message_summary(uid: int | str, msg: email.message.Message) -> dict[str, Any]:
    """将邮件消息构建为摘要字典。

    Args:
        uid: 邮件 UID
        msg: email.message.Message 对象

    Returns:
        摘要字典
    """
    subject = decode_header_value(msg.get("Subject", ""))
    from_raw = decode_header_value(msg.get("From", ""))
    from_name, from_addr = extract_email_address(from_raw)
    to_raw = decode_header_value(msg.get("To", ""))
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


def build_message_detail(uid: int | str, msg: email.message.Message) -> dict[str, Any]:
    """将邮件消息构建为详情字典（含正文和附件）。

    Args:
        uid: 邮件 UID
        msg: email.message.Message 对象

    Returns:
        详情字典
    """
    summary = build_message_summary(uid, msg)
    summary["body"] = get_text_body(msg)

    # 附件列表
    attachments: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                filename = part.get_filename()
                if filename:
                    attachments.append(decode_header_value(filename))
    summary["attachments"] = attachments

    return summary


# ======================================================================
# IMAP 同步操作（在 to_thread 中执行）
# ======================================================================


def imap_list(
    cfg: Any,
    folder: str,
    limit: int,
    offset: int,
    unseen_only: bool,
) -> dict[str, Any]:
    """同步 IMAP 列出邮件（在 to_thread 中执行）。"""
    import imapclient

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
                summary = build_message_summary(uid, msg)
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


def imap_read(uid: int, cfg: Any, folder: str, mark_seen: bool) -> dict[str, Any]:
    """同步 IMAP 读取邮件详情（在 to_thread 中执行）。"""
    import imapclient

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
        detail = build_message_detail(uid, msg)

        logger.info(f"读取邮件: UID {uid} - {detail['subject']}")
        return detail
    finally:
        server.logout()


def imap_search(
    cfg: Any,
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
                emails.append(build_message_summary(uid, msg))

        logger.info(f"搜索邮件: {folder} ({len(emails)}/{total})")
        return {
            "emails": emails,
            "total": total,
            "folder": folder,
        }
    finally:
        server.logout()


def imap_delete(cfg: Any, uids: list[int], folder: str) -> dict[str, Any]:
    """同步 IMAP 删除邮件（在 to_thread 中执行）。"""
    import imapclient

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


def imap_move(cfg: Any, uid: int, source_folder: str, dest_folder: str) -> dict[str, Any]:
    """同步 IMAP 移动邮件（在 to_thread 中执行）。"""
    import imapclient

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


def imap_folders(cfg: Any) -> dict[str, Any]:
    """同步 IMAP 获取文件夹列表（在 to_thread 中执行）。"""
    import imapclient

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
