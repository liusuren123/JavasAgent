"""桌面应用启动器。

通过名称、路径或协议启动应用程序，
支持模糊匹配、进程检测、窗口置前和优雅关闭。

依赖：仅标准库 + loguru（无新增依赖）。
Windows 平台使用 subprocess、os、ctypes。
"""

from __future__ import annotations

import os
import subprocess
from difflib import SequenceMatcher
from typing import Any

from loguru import logger

from src.tools.app_launcher_models import AppInfo, LaunchResult

# ── 常量 ────────────────────────────────────────────────────

_FUZZY_THRESHOLD = 0.5

if os.name == "nt":
    _PF = os.environ.get("ProgramFiles", r"C:\Program Files")
    _PFX86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    _LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
    _APPDATA = os.environ.get("APPDATA", "")
    _USERPROFILE = os.environ.get("USERPROFILE", "")
    _SEARCH_PATHS = [_PF, _PFX86, os.path.join(_USERPROFILE, "Desktop")]
    _START_MENU_PATHS = [
        os.path.join(_APPDATA, r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(
            os.environ.get("ProgramData", r"C:\ProgramData"),
            r"Microsoft\Windows\Start Menu\Programs",
        ),
    ]
    _URL_PROTOCOLS = ("http:", "https:", "mailto:", "tel:", "ftp:")
    # 别名 → 相对于 Program Files / LocalAppData/Programs 的路径
    _APP_ALIASES: dict[str, str] = {
        "chrome": "Google\\Chrome\\Application\\chrome.exe",
        "google chrome": "Google\\Chrome\\Application\\chrome.exe",
        "firefox": "Mozilla Firefox\\firefox.exe",
        "edge": "Microsoft\\Edge\\Application\\msedge.exe",
        "vscode": "Microsoft VS Code\\Code.exe",
        "visual studio code": "Microsoft VS Code\\Code.exe",
        "notepad": "notepad.exe",
        "calc": "calc.exe",
        "calculator": "calc.exe",
        "explorer": "explorer.exe",
        "word": "Microsoft Office\\WINWORD.EXE",
        "excel": "Microsoft Office\\EXCEL.EXE",
        "powerpoint": "Microsoft Office\\POWERPNT.EXE",
        "weixin": "Tencent\\WeChat\\WeChat.exe",
        "wechat": "Tencent\\WeChat\\WeChat.exe",
        "terminal": "WindowsTerminal.exe",
        "paint": "mspaint.exe",
        "settings": "ms-settings:",
    }
else:
    _SEARCH_PATHS: list[str] = []
    _START_MENU_PATHS: list[str] = []
    _URL_PROTOCOLS = ("http:", "https:", "mailto:", "tel:", "ftp:")
    _APP_ALIASES: dict[str, str] = {}


class AppLauncher:
    """桌面应用启动器。

    Usage::

        launcher = AppLauncher()
        result = await launcher.execute("launch", {"name": "chrome"})
    """

    def __init__(self) -> None:
        self._actions: dict[str, Any] = {
            "launch": self._launch,
            "search": self._search,
            "is_running": self._is_running,
            "bring_to_front": self._bring_to_front,
            "close_app": self._close_app,
            "list_recent": self._list_recent,
        }

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """统一入口。支持 launch / search / is_running / bring_to_front / close_app / list_recent。"""
        handler = self._actions.get(action)
        if handler is None:
            return {
                "success": False,
                "error": f"未知操作: {action}，支持: {', '.join(sorted(self._actions))}",
            }
        try:
            return await handler(params)
        except Exception as exc:
            logger.error("AppLauncher {} 失败: {}", action, exc)
            return {"success": False, "error": str(exc)}

    # ── Action 实现 ─────────────────────────────────────────

    async def _launch(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        path = params.get("path", "")
        args = params.get("args", [])

        if not name and not path:
            return {"success": False, "error": "必须提供 name 或 path 参数"}

        identifier = name or path

        # URL 协议
        if self._is_url_protocol(identifier):
            return await self._launch_protocol(identifier, args)

        # 直接路径
        if path and os.path.isfile(path):
            return await self._launch_process(path, args)
        if name and os.path.isfile(name):
            return await self._launch_process(name, args)

        # 按名称搜索
        if name:
            app_path = self._find_app_path(name)
            if app_path is None:
                return {
                    "success": False,
                    "error": f"找不到应用: {name}。可使用 search 操作搜索已安装程序。",
                }
            # 已在运行则置前
            running_pid = self._get_running_pid(name, app_path)
            if running_pid is not None:
                brought = self._bring_window_to_front_by_pid(running_pid)
                return {
                    "success": True,
                    "data": LaunchResult(
                        success=True, app_name=name, pid=running_pid,
                        path=app_path, already_running=True, brought_to_front=brought,
                    ).__dict__,
                }
            return await self._launch_process(app_path, args)

        return {"success": False, "error": f"找不到应用: {path}"}

    async def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "")
        if not query:
            return {"success": False, "error": "必须提供 query 参数"}

        results = self._search_start_menu(query)
        results.extend(self._search_common_paths(query))

        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for info in results:
            norm = os.path.normcase(info.path)
            if norm not in seen:
                seen.add(norm)
                unique.append({
                    "name": info.name, "path": info.path,
                    "is_running": self._check_process_running(info.name),
                })

        return {"success": True, "data": {"query": query, "matches": unique, "count": len(unique)}}

    async def _is_running(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        if not name:
            return {"success": False, "error": "必须提供 name 参数"}
        running = self._check_process_running(name)
        pid = self._get_running_pid(name) if running else None
        return {"success": True, "data": {"name": name, "is_running": running, "pid": pid}}

    async def _bring_to_front(self, params: dict[str, Any]) -> dict[str, Any]:
        pid = params.get("pid")
        name = params.get("name", "")
        if pid is None and not name:
            return {"success": False, "error": "必须提供 name 或 pid 参数"}
        if pid is None:
            pid = self._get_running_pid(name)
        if pid is None:
            return {"success": False, "error": f"找不到运行中的应用: {name}"}
        ok = self._bring_window_to_front_by_pid(pid)
        result: dict[str, Any] = {"success": ok, "data": {"pid": pid, "name": name}}
        if not ok:
            result["error"] = "窗口置前失败"
        return result

    async def _close_app(self, params: dict[str, Any]) -> dict[str, Any]:
        pid = params.get("pid")
        name = params.get("name", "")
        force = params.get("force", False)
        if pid is None and not name:
            return {"success": False, "error": "必须提供 name 或 pid 参数"}
        if pid is None:
            pid = self._get_running_pid(name)
        if pid is None:
            return {"success": False, "error": f"找不到运行中的应用: {name}"}
        ok = self._close_process(pid, force=force)
        result: dict[str, Any] = {"success": ok, "data": {"pid": pid, "name": name, "force": force}}
        if not ok:
            result["error"] = "关闭应用失败"
        return result

    async def _list_recent(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = params.get("limit", 20)
        shortcuts = self._collect_all_shortcuts()
        timed: list[tuple[float, AppInfo]] = []
        for info in shortcuts:
            try:
                timed.append((os.path.getmtime(info.path), info))
            except OSError:
                continue
        timed.sort(key=lambda x: x[0], reverse=True)
        recent = [{"name": i.name, "path": i.path, "last_modified": t} for t, i in timed[:limit]]
        return {"success": True, "data": {"apps": recent, "count": len(recent)}}

    # ── 应用搜索 ────────────────────────────────────────────

    def _find_app_path(self, name: str) -> str | None:
        """在常见路径中搜索应用。策略：别名精确→别名模糊→开始菜单→路径搜索。"""
        nl = name.lower().strip()

        # 别名精确
        alias = _APP_ALIASES.get(nl)
        if alias:
            resolved = self._resolve_alias(alias)
            if resolved:
                return resolved

        # 别名模糊
        for an, ap in _APP_ALIASES.items():
            if SequenceMatcher(None, nl, an).ratio() >= _FUZZY_THRESHOLD:
                resolved = self._resolve_alias(ap)
                if resolved:
                    return resolved

        # 开始菜单
        menu = self._search_start_menu(name)
        if menu:
            return menu[0].path

        # 常见路径
        common = self._search_common_paths(name)
        if common:
            return common[0].path

        return None

    def _resolve_alias(self, alias: str) -> str | None:
        if os.path.isabs(alias) and os.path.isfile(alias):
            return alias
        if alias.endswith(":") and not os.path.splitext(alias)[1]:
            return alias
        roots = [_PF, _PFX86]
        if _LOCALAPPDATA:
            roots.append(os.path.join(_LOCALAPPDATA, "Programs"))
        for root in roots:
            full = os.path.join(root, alias)
            if os.path.isfile(full):
                return full
        return None

    def _search_start_menu(self, name: str) -> list[AppInfo]:
        results: list[AppInfo] = []
        nl = name.lower()
        for mp in _START_MENU_PATHS:
            if not os.path.isdir(mp):
                continue
            for root, _dirs, files in os.walk(mp):
                for fname in files:
                    if not fname.endswith((".lnk", ".url")):
                        continue
                    aname = os.path.splitext(fname)[0]
                    if nl in aname.lower() or SequenceMatcher(None, nl, aname.lower()).ratio() >= _FUZZY_THRESHOLD:
                        target = self._resolve_lnk(os.path.join(root, fname))
                        results.append(AppInfo(name=aname, path=target or os.path.join(root, fname)))
        return results

    def _search_common_paths(self, name: str) -> list[AppInfo]:
        results: list[AppInfo] = []
        nl = name.lower()
        for sp in _SEARCH_PATHS:
            if not os.path.isdir(sp):
                continue
            try:
                entries = os.listdir(sp)
            except OSError:
                continue
            for entry in entries:
                if nl in entry.lower() or SequenceMatcher(None, nl, entry.lower()).ratio() >= _FUZZY_THRESHOLD:
                    full = os.path.join(sp, entry)
                    if os.path.isdir(full):
                        exe = self._find_exe_in_dir(full, name)
                        if exe:
                            results.append(AppInfo(name=entry, path=exe))
                    elif full.lower().endswith(".exe"):
                        results.append(AppInfo(name=entry, path=full))
        return results

    @staticmethod
    def _find_exe_in_dir(directory: str, name: str) -> str | None:
        nl = name.lower()
        try:
            for root, _dirs, files in os.walk(directory):
                for f in files:
                    if f.lower().endswith(".exe") and nl in f.lower():
                        return os.path.join(root, f)
                if root.count(os.sep) - directory.count(os.sep) >= 2:
                    break
        except OSError:
            pass
        return None

    def _collect_all_shortcuts(self) -> list[AppInfo]:
        results: list[AppInfo] = []
        for mp in _START_MENU_PATHS:
            if not os.path.isdir(mp):
                continue
            for root, _dirs, files in os.walk(mp):
                for fname in files:
                    if not fname.endswith((".lnk", ".url")):
                        continue
                    fpath = os.path.join(root, fname)
                    aname = os.path.splitext(fname)[0]
                    target = self._resolve_lnk(fpath)
                    results.append(AppInfo(name=aname, path=target or fpath))
        return results

    @staticmethod
    def _resolve_lnk(lnk_path: str) -> str | None:
        """解析 .lnk 快捷方式的目标路径（使用 PowerShell）。"""
        if os.name != "nt":
            return None
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk_path}').TargetPath"],
                capture_output=True, text=True, timeout=5,
            )
            target = r.stdout.strip()
            return target if target else None
        except Exception as exc:
            logger.debug("解析快捷方式失败 {}: {}", lnk_path, exc)
            return None

    # ── 进程管理 ────────────────────────────────────────────

    async def _launch_process(self, path: str, args: list[str] | None = None) -> dict[str, Any]:
        try:
            cmd = [path] + (args or [])
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)
            app_name = os.path.splitext(os.path.basename(path))[0]
            logger.info("已启动应用: {} (PID={})", app_name, proc.pid)
            return {"success": True, "data": LaunchResult(
                success=True, app_name=app_name, pid=proc.pid, path=path).__dict__}
        except FileNotFoundError:
            return {"success": False, "error": f"可执行文件不存在: {path}"}
        except Exception as exc:
            return {"success": False, "error": f"启动失败: {exc}"}

    async def _launch_protocol(self, url: str, args: list[str] | None = None) -> dict[str, Any]:
        try:
            if os.name == "nt":
                os.startfile(url)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", url])
            return {"success": True, "data": {"app_name": url.split(":")[0], "path": url, "protocol_launch": True}}
        except Exception as exc:
            return {"success": False, "error": f"协议启动失败: {exc}"}

    @staticmethod
    def _check_process_running(name: str) -> bool:
        try:
            import psutil
            nl = name.lower()
            for proc in psutil.process_iter(["name"]):
                try:
                    if nl in (proc.info.get("name") or "").lower():
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except ImportError:
            logger.warning("psutil 未安装，无法检查进程状态")
        except Exception as exc:
            logger.debug("检查进程状态失败: {}", exc)
        return False

    @staticmethod
    def _get_running_pid(name: str, path: str = "") -> int | None:
        try:
            import psutil
            nl = name.lower()
            pl = path.lower() if path else ""
            for proc in psutil.process_iter(["name", "exe", "pid"]):
                try:
                    pn = (proc.info.get("name") or "").lower()
                    if nl in pn:
                        if pl:
                            pe = (proc.info.get("exe") or "").lower()
                            if pl in pe:
                                return proc.info["pid"]
                        else:
                            return proc.info["pid"]
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except ImportError:
            logger.warning("psutil 未安装，无法获取进程 PID")
        except Exception as exc:
            logger.debug("获取进程 PID 失败: {}", exc)
        return None

    @staticmethod
    def _bring_window_to_front_by_pid(pid: int) -> bool:
        """将指定 PID 的进程窗口置于前台（Windows API）。"""
        if os.name != "nt":
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            target_hwnd: list[int] = []

            def _cb(hwnd: int, _lparam: int) -> bool:
                wnd_pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wnd_pid))
                if wnd_pid.value == pid and user32.IsWindowVisible(hwnd):
                    target_hwnd.append(hwnd)
                return True

            user32.EnumWindows(WNDENUMPROC(_cb), 0)
            if not target_hwnd:
                return False
            user32.ShowWindow(target_hwnd[0], 9)  # SW_RESTORE
            user32.SetForegroundWindow(target_hwnd[0])
            return True
        except Exception as exc:
            logger.error("窗口置前失败: {}", exc)
            return False

    @staticmethod
    def _close_process(pid: int, force: bool = False) -> bool:
        try:
            import psutil
            proc = psutil.Process(pid)
            if force:
                proc.kill()
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except psutil.TimeoutExpired:
                    proc.kill()
            return True
        except psutil.NoSuchProcess:
            return True
        except psutil.AccessDenied:
            return False
        except ImportError:
            if os.name == "nt":
                flag = ["/F"] if force else []
                r = subprocess.run(["taskkill", *flag, "/PID", str(pid)], capture_output=True)
                return r.returncode == 0
            return False
        except Exception as exc:
            logger.error("关闭进程失败: {}", exc)
            return False

    @staticmethod
    def _is_url_protocol(text: str) -> bool:
        return any(text.lower().startswith(p) for p in _URL_PROTOCOLS)
