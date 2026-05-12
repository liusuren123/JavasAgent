# -*- coding: utf-8 -*-
"""ChatWindow 单元测试。

注意：tkinter 在无显示环境下可能不可用，使用 mock 替代。
"""

from unittest.mock import MagicMock, patch

import pytest

from src.daemon.chat_window import ChatWindow


class TestChatWindowInit:
    """ChatWindow.__init__ 测试。"""

    def test_callbacks_stored(self):
        cb = MagicMock()
        win = ChatWindow(on_send_message=cb)
        assert win._on_send_message is cb

    def test_default_size(self):
        win = ChatWindow()
        assert win._width == 600
        assert win._height == 400
        assert win._always_on_top is True

    def test_custom_size(self):
        win = ChatWindow(width=800, height=600, always_on_top=False)
        assert win._width == 800
        assert win._height == 600
        assert win._always_on_top is False

    def test_initial_state(self):
        win = ChatWindow()
        assert win.is_visible is False
        assert win._root is None


class TestChatWindowOperations:
    """ChatWindow 操作测试（mock tkinter）。"""

    def test_add_message_without_root(self):
        """窗口未初始化时 add_message 不崩溃。"""
        win = ChatWindow()
        win.add_message("agent", "测试消息")  # 不报错

    def test_set_status_without_root(self):
        win = ChatWindow()
        win.set_status("运行中")  # 不报错

    def test_clear_input_without_root(self):
        win = ChatWindow()
        win.clear_input()  # 不报错

    def test_hide_without_root(self):
        win = ChatWindow()
        win.hide()  # 不报错
        assert win.is_visible is False

    def test_close_without_root(self):
        win = ChatWindow()
        win.close()  # 不报错

    def test_show_creates_root(self):
        """show 在 tkinter 可用时创建 root。"""
        win = ChatWindow()
        with patch("src.daemon.chat_window._TK_AVAILABLE", True), \
             patch.object(win, "_build_ui") as mock_build:
            def fake_build():
                win._root = MagicMock()
            mock_build.side_effect = fake_build

            win.show()
            assert win.is_visible is True
            assert win._root is not None
            mock_build.assert_called_once()

    def test_send_message_callback(self):
        """发送消息触发回调。"""
        cb = MagicMock()
        win = ChatWindow(on_send_message=cb)
        win._input_var = MagicMock()
        win._input_var.get.return_value = "你好"
        win._text_area = MagicMock()

        win._send_message()
        cb.assert_called_once_with("你好")

    def test_send_message_empty_text(self):
        """空消息不触发回调。"""
        cb = MagicMock()
        win = ChatWindow(on_send_message=cb)
        win._input_var = MagicMock()
        win._input_var.get.return_value = "  "

        win._send_message()
        cb.assert_not_called()

    def test_on_close_hides(self):
        """关闭窗口 = 隐藏。"""
        win = ChatWindow()
        win._root = MagicMock()
        win._visible = True
        win._on_close()
        assert win.is_visible is False
