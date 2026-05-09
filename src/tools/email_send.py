"""邮件 SMTP 发送模块。

提供邮件发送功能，包括消息构建和 SMTP 投递。
"""

from __future__ import annotations

import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from loguru import logger

from src.utils.path_safety import PathSafetyError


def smtp_send(
    cfg: Any,
    msg: MIMEMultipart,
    recipients: list[str],
) -> dict[str, Any]:
    """同步 SMTP 发送（在 to_thread 中执行）。

    Args:
        cfg: EmailConfig 实例
        msg: 构建好的邮件消息
        recipients: 所有收件人列表

    Returns:
        发送结果字典
    """
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
