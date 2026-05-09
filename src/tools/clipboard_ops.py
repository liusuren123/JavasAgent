"""剪贴板管理工具。

提供剪贴板读取、写入、清空、监控能力。
支持文本、图片（Base64）、文件列表等格式。
"""

from __future__ import annotations

import base64
import io
import struct
import threading
import time
from typing import Any

from loguru import logger


class ClipboardOps:
    """剪贴板管理工具。"""

    def __init__(self) -> None:
        self._watch_running = False
        self._watch_thread: threading.Thread | None = None
        self._watch_changes: list[dict[str, Any]] = []
        self._last_clipboard_text: str | None = None

    # ------------------------------------------------------------------
    # 统一入口
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict[str, Any]) -> Any:
        """执行剪贴板操作。

        Args:
            action: 操作类型 (read / write_text / write_files / clear / watch)
            params: 操作参数
        """
        handlers = {
            "read": self._read,
            "write_text": self._write_text,
            "write_files": self._write_files,
            "clear": self._clear,
            "watch": self._watch,
        }

        handler = handlers.get(action)
        if handler is None:
            logger.error(f"未知剪贴板操作: {action}")
            return {"error": f"未知操作: {action}，支持: {', '.join(handlers.keys())}"}

        return await handler(params)

    # ------------------------------------------------------------------
    # read — 读取剪贴板
    # ------------------------------------------------------------------

    async def _read(self, params: dict[str, Any]) -> dict[str, Any]:
        """读取剪贴板内容，自动识别文本 / 图片 / 文件列表。"""
        results: list[dict[str, Any]] = []

        # 1) 尝试读取文件列表
        file_list = self._read_file_list()
        if file_list is not None:
            results.append({"format": "files", "files": file_list})

        # 2) 尝试读取图片
        image_info = self._read_image()
        if image_info is not None:
            results.append(image_info)

        # 3) 尝试读取文本
        text = self._read_text()
        if text is not None:
            results.append({"format": "text", "content": text})

        if not results:
            return {"format": "empty", "content": None}

        # 只有一种格式时直接返回
        if len(results) == 1:
            return results[0]

        return {"format": "mixed", "contents": results}

    def _read_text(self) -> str | None:
        """读取剪贴板文本内容。"""
        try:
            import pyperclip
            return pyperclip.paste() or None
        except pyperclip.PyperclipException:
            return None
        except Exception:
            return None

    def _read_image(self) -> dict[str, Any] | None:
        """读取剪贴板中的图片（Windows）。"""
        try:
            import win32clipboard
            from PIL import Image

            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB):
                    data = win32clipboard.GetClipboardData(win32clipboard.CF_DIB)
                    if not data:
                        return None
                    img = self._dib_to_image(data)
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                    return {
                        "format": "image",
                        "width": img.width,
                        "height": img.height,
                        "base64": b64,
                        "size_bytes": len(buf.getvalue()),
                    }
                return None
            finally:
                win32clipboard.CloseClipboard()
        except ImportError:
            logger.debug("win32clipboard 或 Pillow 不可用，跳过图片读取")
            return None
        except Exception as exc:
            logger.debug(f"图片读取失败: {exc}")
            return None

    @staticmethod
    def _dib_to_image(dib_data: bytes) -> "Image.Image":
        """将 CF_DIB 数据转换为 PIL Image。"""
        from PIL import Image

        # BITMAPINFOHEADER: 前 40 字节
        header_size = struct.unpack_from("<I", dib_data, 0)[0]
        if header_size < 40:
            msg = f"无效 DIB header size: {header_size}"
            raise ValueError(msg)

        width = struct.unpack_from("<i", dib_data, 4)[0]
        height = abs(struct.unpack_from("<i", dib_data, 8)[0])
        bit_count = struct.unpack_from("<H", dib_data, 14)[0]

        # 构造 BMP 文件
        bmp_header = struct.pack(
            "<2sIHHI",
            b"BM",
            14 + len(dib_data),  # 文件大小
            0,  # reserved1
            0,  # reserved2
            14 + header_size,  # pixel data offset
        )
        bmp_data = bmp_header + dib_data

        # 对于 32-bit BGRA，需要转换为 RGBA
        if bit_count == 32:
            img = Image.open(io.BytesIO(bmp_data))
            if img.mode == "BGRA":
                img = img.convert("RGBA")
            return img

        return Image.open(io.BytesIO(bmp_data))

    def _read_file_list(self) -> list[str] | None:
        """读取剪贴板中的文件列表（Windows CF_HDROP）。"""
        try:
            import win32clipboard

            win32clipboard.OpenClipboard()
            try:
                cf_hdrop = 15  # CF_HDROP
                if not win32clipboard.IsClipboardFormatAvailable(cf_hdrop):
                    return None
                data = win32clipboard.GetClipboardData(cf_hdrop)
                if isinstance(data, tuple):
                    return list(data)
                if isinstance(data, str):
                    return [data]
                return None
            finally:
                win32clipboard.CloseClipboard()
        except ImportError:
            return None
        except Exception as exc:
            logger.debug(f"文件列表读取失败: {exc}")
            return None

    # ------------------------------------------------------------------
    # write_text
    # ------------------------------------------------------------------

    async def _write_text(self, params: dict[str, Any]) -> dict[str, Any]:
        """写入文本到剪贴板。"""
        text = params.get("text", "")
        if not isinstance(text, str):
            return {"error": "text 参数必须是字符串"}
        try:
            import pyperclip
            pyperclip.copy(text)
            logger.info(f"已写入剪贴板文本 ({len(text)} 字符)")
            return {"success": True, "format": "text", "length": len(text)}
        except pyperclip.PyperclipException as exc:
            return {"error": f"剪贴板写入失败: {exc}"}

    # ------------------------------------------------------------------
    # write_files
    # ------------------------------------------------------------------

    async def _write_files(self, params: dict[str, Any]) -> dict[str, Any]:
        """写入文件路径列表到剪贴板（模拟复制文件，仅 Windows）。"""
        files = params.get("files", [])
        if not isinstance(files, list) or not files:
            return {"error": "files 参数必须是非空字符串列表"}

        try:
            import win32clipboard

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                # 使用 DROPFILES 结构写入文件列表
                drop_files = self._build_dropfiles(files)
                win32clipboard.SetClipboardData(
                    win32clipboard.CF_HDROP, drop_files
                )
                logger.info(f"已写入剪贴板文件列表 ({len(files)} 个文件)")
                return {"success": True, "format": "files", "count": len(files)}
            finally:
                win32clipboard.CloseClipboard()
        except ImportError:
            return {"error": "write_files 需要 pywin32，当前环境不可用"}
        except Exception as exc:
            return {"error": f"文件列表写入失败: {exc}"}

    @staticmethod
    def _build_dropfiles(file_paths: list[str]) -> bytes:
        """构建 DROPFILES 结构体用于 CF_HDROP。"""
        # DROPFILES header: 20 bytes
        # offset 0: DWORD dwSize = 20 (0x14)
        # offset 4: POINT pt (x=0, y=0) = 8 bytes
        # offset 12: BOOL fNC = 0
        # offset 16: BOOL fWide = 1 (Unicode)
        header = struct.pack("<IiiII", 20, 0, 0, 0, 1)
        paths = "\0".join(file_paths) + "\0\0"
        paths_bytes = paths.encode("utf-16-le")
        return header + paths_bytes

    # ------------------------------------------------------------------
    # clear
    # ------------------------------------------------------------------

    async def _clear(self, params: dict[str, Any]) -> dict[str, Any]:
        """清空剪贴板。"""
        try:
            import win32clipboard

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                logger.info("剪贴板已清空")
                return {"success": True, "action": "clear"}
            finally:
                win32clipboard.CloseClipboard()
        except ImportError:
            # 退回到 pyperclip 写空字符串
            try:
                import pyperclip
                pyperclip.copy("")
                return {"success": True, "action": "clear"}
            except Exception:
                return {"error": "清空剪贴板失败：无可用剪贴板后端"}
        except Exception as exc:
            return {"error": f"清空剪贴板失败: {exc}"}

    # ------------------------------------------------------------------
    # watch — 监控剪贴板变化
    # ------------------------------------------------------------------

    async def _watch(self, params: dict[str, Any]) -> dict[str, Any]:
        """监控剪贴板变化。

        支持子操作:
        - start:  开始轮询监控
        - stop:   停止监控
        - changes: 获取已记录的变化列表
        """
        sub = params.get("sub", "changes")

        if sub == "start":
            return self._watch_start(params)
        if sub == "stop":
            return self._watch_stop()
        if sub == "changes":
            return {"changes": list(self._watch_changes)}

        return {"error": f"未知 watch 子操作: {sub}，支持: start / stop / changes"}

    def _watch_start(self, params: dict[str, Any]) -> dict[str, Any]:
        """启动后台轮询监控。"""
        if self._watch_running:
            return {"status": "already_running", "changes_count": len(self._watch_changes)}

        interval = params.get("interval", 0.5)
        self._watch_running = True
        self._watch_changes.clear()
        self._last_clipboard_text = self._read_text()

        def _poll() -> None:
            while self._watch_running:
                try:
                    current = self._read_text()
                    if current != self._last_clipboard_text:
                        self._last_clipboard_text = current
                        self._watch_changes.append({
                            "timestamp": time.time(),
                            "format": "text",
                            "preview": (current[:200] if current else None),
                        })
                except Exception:
                    pass
                time.sleep(interval)

        self._watch_thread = threading.Thread(target=_poll, daemon=True)
        self._watch_thread.start()
        logger.info(f"剪贴板监控已启动，轮询间隔 {interval}s")
        return {"status": "started", "interval": interval}

    def _watch_stop(self) -> dict[str, Any]:
        """停止后台监控。"""
        if not self._watch_running:
            return {"status": "not_running", "changes_count": 0}

        self._watch_running = False
        if self._watch_thread and self._watch_thread.is_alive():
            self._watch_thread.join(timeout=2.0)
        self._watch_thread = None

        count = len(self._watch_changes)
        logger.info(f"剪贴板监控已停止，共记录 {count} 次变化")
        return {"status": "stopped", "changes_count": count}
