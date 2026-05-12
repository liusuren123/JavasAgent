# -*- coding: utf-8 -*-
"""对话窗口 — 基于 tkinter。

热键呼出的简易对话界面，支持发送消息和显示回复。
所有 UI 操作通过 root.after() 调度到 tkinter 主线程，确保线程安全。
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

try:
    import tkinter as tk
    _TK_AVAILABLE = True
except ImportError:
    tk = None  # type: ignore
    _TK_AVAILABLE = False

logger = logging.getLogger("javas.daemon.chat_window")


class ChatWindow:
    """tkinter 对话窗口。

    用法:
        win = ChatWindow(on_send_message=handle_send)
        win.show()
        ...
        win.add_message("agent", "你好！")
        ...
        win.hide()  # 隐藏（不退出）
    """

    def __init__(
        self,
        on_send_message: Optional[Callable[[str], None]] = None,
        width: int = 600,
        height: int = 400,
        always_on_top: bool = True,
    ) -> None:
        self._on_send_message = on_send_message
        self._width = width
        self._height = height
        self._always_on_top = always_on_top

        self._root: Optional[tk.Tk] = None
        self._text_area: Optional[tk.Text] = None
        self._input_var: Optional[tk.StringVar] = None
        self._input_entry: Optional[tk.Entry] = None
        self._status_var: Optional[tk.StringVar] = None
        self._thread: Optional[threading.Thread] = None
        self._visible = False

    @property
    def is_visible(self) -> bool:
        return self._visible

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """构建窗口组件。"""
        if not _TK_AVAILABLE:
            logger.warning("tkinter 不可用，对话窗口无法创建")
            return

        self._root = tk.Tk()
        self._root.title("JavasAgent")
        self._root.geometry(f"{self._width}x{self._height}")
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        if self._always_on_top:
            self._root.attributes("-topmost", True)

        # 消息显示区域
        text_frame = tk.Frame(self._root)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))

        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._text_area = tk.Text(
            text_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            yscrollcommand=scrollbar.set,
            font=("Microsoft YaHei", 10),
            bg="#f5f5f5",
        )
        self._text_area.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._text_area.yview)

        # 配置标签样式
        self._text_area.tag_configure("agent", foreground="#1a73e8")
        self._text_area.tag_configure("user", foreground="#333333")
        self._text_area.tag_configure("system", foreground="#999999")

        # 输入区域
        input_frame = tk.Frame(self._root)
        input_frame.pack(fill=tk.X, padx=8, pady=(4, 8))

        self._input_var = tk.StringVar()
        self._input_entry = tk.Entry(
            input_frame,
            textvariable=self._input_var,
            font=("Microsoft YaHei", 10),
        )
        self._input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self._input_entry.bind("<Return>", lambda e: self._send_message())

        send_btn = tk.Button(
            input_frame, text="发送", command=self._send_message, width=8
        )
        send_btn.pack(side=tk.RIGHT)

        # 状态栏
        self._status_var = tk.StringVar(value="就绪")
        status_bar = tk.Label(
            self._root,
            textvariable=self._status_var,
            anchor=tk.W,
            relief=tk.SUNKEN,
            font=("Microsoft YaHei", 8),
            fg="#666666",
        )
        status_bar.pack(fill=tk.X, padx=0, pady=0, side=tk.BOTTOM)

        # 初始欢迎消息
        self._append_text("🤖: 你好，我是 JavasAgent\n", "agent")

    # ------------------------------------------------------------------
    # 显示 / 隐藏
    # ------------------------------------------------------------------
    def show(self) -> None:
        """显示窗口（独立线程运行 mainloop）。"""
        if not _TK_AVAILABLE:
            logger.warning("tkinter 不可用，对话窗口无法显示")
            return

        if self._root is None:
            self._build_ui()
            if self._root is None:
                return
            self._thread = threading.Thread(
                target=self._root.mainloop, name="chat-window", daemon=True
            )
            self._thread.start()
        else:
            # 已构建过，重新显示
            try:
                self._root.after(0, self._root.deiconify)
            except Exception:
                pass

        self._visible = True
        logger.info("对话窗口已显示")

    def hide(self) -> None:
        """隐藏窗口（不销毁）。"""
        if self._root is not None:
            try:
                self._root.after(0, self._root.withdraw)
            except Exception:
                pass
        self._visible = False
        logger.info("对话窗口已隐藏")

    def close(self) -> None:
        """关闭并销毁窗口。"""
        if self._root is not None:
            try:
                self._root.after(0, self._root.destroy)
            except Exception:
                pass
            self._root = None
        self._visible = False

    # ------------------------------------------------------------------
    # 消息操作
    # ------------------------------------------------------------------
    def add_message(self, role: str, text: str) -> None:
        """追加消息到显示区。

        Args:
            role: "agent" / "user" / "system"
            text: 消息文本
        """
        prefix_map = {"agent": "🤖: ", "user": "👤: ", "system": "⚙️: "}
        prefix = prefix_map.get(role, "  ")
        full_text = f"{prefix}{text}\n"

        if self._root is not None and self._text_area is not None:
            try:
                self._root.after(0, self._append_text, full_text, role)
            except Exception:
                pass
        else:
            logger.debug("窗口未初始化，消息未显示: %s", text[:50])

    def set_status(self, text: str) -> None:
        """更新底部状态栏。"""
        if self._status_var is not None and self._root is not None:
            try:
                self._root.after(0, self._status_var.set, text)
            except Exception:
                pass

    def clear_input(self) -> None:
        """清空输入框。"""
        if self._input_var is not None:
            self._input_var.set("")

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _append_text(self, text: str, tag: str = "") -> None:
        """线程安全地向文本区追加内容。"""
        if self._text_area is None:
            return
        self._text_area.config(state=tk.NORMAL)
        self._text_area.insert(tk.END, text, tag)
        self._text_area.config(state=tk.DISABLED)
        self._text_area.see(tk.END)

    def _send_message(self) -> None:
        """发送按钮/回车回调。"""
        if self._input_var is None:
            return

        text = self._input_var.get().strip()
        if not text:
            return

        # 显示用户消息
        self.add_message("user", text)
        self.clear_input()

        # 触发回调
        if self._on_send_message:
            try:
                self._on_send_message(text)
            except Exception as exc:
                logger.error("send_message 回调异常: %s", exc)

    def _on_close(self) -> None:
        """窗口关闭 = 隐藏。"""
        self.hide()
