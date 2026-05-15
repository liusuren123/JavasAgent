"""
E2E Test: Notepad Text Edit Scenario
======================================
端到端测试：打开记事本 → 输入中文文本 → 保存到指定路径 → 验证文件内容

使用 pyautogui + PIL 实现桌面操作，独立于 JavasAgent Agent 框架。
屏幕分辨率：3840×2160。

每步都有视觉验证（截图 + Ollama qwen3-vl 分析），脚本判定 vs 视觉判定对比。

失败分类：
  - PERCEPTION: 感知失败（无法识别屏幕状态）
  - LOCATION: 定位失败（无法找到目标元素位置）
  - OPERATION: 操作失败（操作执行了但效果不对）
  - DECISION: 决策失败（策略或时序错误）
"""

import os
import sys
import time
import json
import subprocess
import traceback
from pathlib import Path
from datetime import datetime

# Fix Windows GBK console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pyautogui
import pyperclip
import requests
from PIL import Image

# ─── 配置 ─────────────────────────────────────────────
SCREEN_W, SCREEN_H = 3840, 2160
TEST_TEXT = "JavasAgent端到端测试：记事本中文输入验证\n第二行：Hello World!\n第三行：测试完成。"
SAVE_FILE_PATH = Path(os.environ.get("TEMP", "C:\\Temp")) / "javasagent_notepad_test.txt"
WAIT_SHORT = 1   # 秒
WAIT_MEDIUM = 3  # 秒
WAIT_LONG = 5    # 秒
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen3-vl"

# 路径
EVIDENCE_DIR = Path(__file__).resolve().parent.parent.parent / "test-evidence" / "e2e-notepad"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# pyautogui 安全设置
pyautogui.PAUSE = 0.5
pyautogui.FAILSAFE = True


# ─── 视觉验证（Ollama qwen3-vl）──────────────────────────
def analyze_screenshot(image_path: str, prompt: str, timeout: int = 30) -> dict:
    """调用本地 Ollama qwen3-vl 分析截图，返回判断结果。

    Args:
        image_path: 截图文件路径
        prompt: 给视觉模型的提示词
        timeout: 请求超时秒数

    Returns:
        {"success": bool, "analysis": str, "raw_response": str}
    """
    import base64

    try:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 300},
        }

        resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        response_text = data.get("response", "").strip()

        # 移除 qwen3 的 <think/> 标签内容（如果存在）
        import re
        response_text = re.sub(r'<think[\s\S]*?</think\s*>', '', response_text).strip()

        # 解析模型回复：如果包含 [YES] 或 "成功" 类关键词 → 通过
        success_keywords = ["[YES]", "[PASS]", "成功", "已打开", "已输入", "已保存",
                            "文本已显示", "记事本已打开", "文件内容匹配", "内容一致"]
        fail_keywords = ["[NO]", "[FAIL]", "失败", "未打开", "未输入", "未保存",
                         "看不到", "不存在", "不匹配", "错误"]

        is_success = any(kw in response_text for kw in success_keywords)
        is_fail = any(kw in response_text for kw in fail_keywords)

        if is_fail and not is_success:
            success = False
        elif is_success:
            success = True
        else:
            # 无法明确判断，保守标记为 unknown
            success = None

        return {"success": success, "analysis": response_text, "raw_response": response_text}

    except requests.exceptions.ConnectionError:
        return {"success": None, "analysis": "Ollama 服务未启动，无法视觉验证", "raw_response": ""}
    except Exception as e:
        return {"success": None, "analysis": f"视觉验证异常: {e}", "raw_response": ""}


# ─── 工具函数 ──────────────────────────────────────────
def screenshot(name: str) -> Path:
    """截图并保存到 evidence 目录"""
    path = EVIDENCE_DIR / f"{name}.png"
    img = pyautogui.screenshot()
    img.save(path)
    print(f"  📸 截图已保存: {path.name}")
    return path


def classify_failure(context: str) -> str:
    """根据上下文分类失败原因"""
    ctx = context.lower()
    if any(k in ctx for k in ["not found", "找不到", "无法识别", "screenshot", "感知", "看不到"]):
        return "PERCEPTION"
    if any(k in ctx for k in ["位置", "坐标", "定位", "click at", "locate"]):
        return "LOCATION"
    if any(k in ctx for k in ["点击", "输入", "type", "click", "press", "操作", "粘贴", "保存"]):
        return "OPERATION"
    return "DECISION"


def wait(seconds: float, desc: str = ""):
    """等待并打印进度"""
    label = f" ({desc})" if desc else ""
    print(f"  ⏳ 等待 {seconds}s{label}...")
    time.sleep(seconds)


def paste_text(text: str):
    """通过剪贴板粘贴中文文本"""
    pyperclip.copy(text)
    time.sleep(0.1)
    pyautogui.hotkey("ctrl", "v")


class StepResult:
    """单个步骤的结果"""

    def __init__(self, step_name: str):
        self.step_name = step_name
        self.success = False
        self.script_success = False     # 脚本自动判定
        self.vision_success = None      # 视觉模型判定（None=未验证）
        self.vision_analysis = ""       # 视觉模型分析文本
        self.start_time = time.time()
        self.end_time = None
        self.screenshot_path = None
        self.error = None
        self.failure_category = None
        self.detail = ""

    def finish(self, success: bool, detail: str = "", error: str = None):
        self.success = success
        self.script_success = success
        self.end_time = time.time()
        self.detail = detail
        self.error = error
        if not success and error:
            self.failure_category = classify_failure(error)

    def set_vision_result(self, vision_success: bool, analysis: str):
        """设置视觉验证结果"""
        self.vision_success = vision_success
        self.vision_analysis = analysis
        # 最终结果以视觉验证为准（如果视觉验证可用）
        if vision_success is not None:
            self.success = vision_success
            if not vision_success and not self.failure_category:
                self.failure_category = classify_failure(analysis)

    def to_dict(self) -> dict:
        return {
            "step": self.step_name,
            "script_success": self.script_success,
            "vision_success": self.vision_success,
            "final_success": self.success,
            "duration_sec": round(self.end_time - self.start_time, 2) if self.end_time else None,
            "screenshot": self.screenshot_path.name if self.screenshot_path else None,
            "detail": self.detail,
            "error": self.error,
            "failure_category": self.failure_category,
            "vision_analysis": self.vision_analysis[:200] if self.vision_analysis else "",
        }


# ─── 测试步骤 ──────────────────────────────────────────
def bring_to_front(window_title: str) -> bool:
    """使用 Win32 API 将指定标题的窗口置于前台。
    使用部分匹配，window_title 只需是窗口标题的子串。"""
    try:
        import ctypes
        user32 = ctypes.windll.user32

        # 枚举所有窗口找匹配的
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        found_hwnd = [0]

        def enum_callback(hwnd, _):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                if window_title in title:
                    found_hwnd[0] = hwnd
                    return False  # stop enumeration
            return True

        user32.EnumWindows(EnumWindowsProc(enum_callback), 0)
        if found_hwnd[0]:
            SW_RESTORE = 9
            user32.ShowWindow(found_hwnd[0], SW_RESTORE)
            user32.SetForegroundWindow(found_hwnd[0])
            return True

        return False
    except Exception:
        return False


def bring_notepad_front() -> bool:
    """将记事本窗口置于前台（尝试多种标题匹配）"""
    # Windows 11 记事本标题格式："无标题 - Notepad" 或 "*无标题 - Notepad"（有未保存修改时）
    for title in ["Notepad", "无标题", "记事本"]:
        if bring_to_front(title):
            return True
    return False


def step_1_open_notepad(results: list) -> StepResult:
    """Step 1: 打开记事本"""
    sr = StepResult("打开记事本")
    print("\n[Step 1] 打开记事本")

    try:
        # 关闭已有的记事本实例（避免干扰）
        subprocess.run(["taskkill", "/F", "/IM", "notepad.exe"],
                        capture_output=True, timeout=5)
        wait(1, "等待旧进程关闭")

        # 用 os.startfile 打开记事本（更可靠）
        os.startfile("notepad.exe")
        wait(WAIT_MEDIUM, "等待记事本启动")

        # 尝试将记事本窗口置于前台
        bring_notepad_front()
        wait(1, "等待窗口前台切换")
        sr.screenshot_path = screenshot("step1_notepad_opened")

        # 视觉验证：截图分析记事本是否打开且可见
        vision = analyze_screenshot(
            str(sr.screenshot_path),
            "请判断屏幕上是否可以看到 Windows 记事本(Notepad)窗口。"
            "Windows 11 记事本可能是深色主题。"
            "标题栏通常显示'无标题 - Notepad'或类似文本。"
            "如果能看到记事本窗口，回复 [YES] 记事本已打开；"
            "如果完全看不到记事本窗口，回复 [NO] 未检测到记事本窗口。"
        )
        sr.set_vision_result(vision["success"], vision["analysis"])
        print(f"  👁️ 视觉判定: {'通过' if vision['success'] else '未通过'} — {vision['analysis'][:80]}")

        if sr.script_success is True:
            sr.detail = "记事本已启动（脚本判定通过）"

        print(f"  {'✓' if sr.success else '✗'} Step 1 {'通过' if sr.success else '失败'}")
    except Exception as e:
        sr.finish(False, error=str(e))
        screenshot("step1_error")
        print(f"  ✗ Step 1 异常: {e}")

    results.append(sr)
    return sr


def step_2_type_chinese(results: list) -> StepResult:
    """Step 2: 输入中文文本"""
    sr = StepResult("输入中文文本")
    print(f"\n[Step 2] 输入中文文本")

    try:
        # 用 Win32 API 将记事本置于前台（比坐标点击可靠）
        bring_notepad_front()
        wait(WAIT_SHORT, "等待记事本获得焦点")
        sr.screenshot_path = screenshot("step2_before_input")

        # 视觉验证：记事本是否在前台
        vision_focus = analyze_screenshot(
            str(sr.screenshot_path),
            "请判断当前屏幕上的记事本窗口是否处于活跃(前台)状态（标题栏是否高亮/激活）。"
            "如果记事本在前台（标题栏高亮），回复 [YES] 记事本已获得焦点；否则回复 [NO]。"
        )
        print(f"  👁️ 焦点检查: {'通过' if vision_focus['success'] else '未通过'} — {vision_focus['analysis'][:80]}")

        # 输入中文文本（剪贴板方式）
        # 先全选+删除清空已有内容（防止会话恢复残留）
        pyautogui.hotkey("ctrl", "a")
        wait(0.3)
        pyautogui.press("delete")
        wait(0.3)

        paste_text(TEST_TEXT)
        wait(WAIT_SHORT, "等待文本输入")
        sr.screenshot_path = screenshot("step2_text_typed")

        # 视觉验证：文本是否出现在记事本中
        vision = analyze_screenshot(
            str(sr.screenshot_path),
            "请判断记事本窗口中是否显示了中文文本（包括'JavasAgent端到端测试'、'Hello World'等内容）。"
            "如果可以看到这些文本内容，回复 [YES] 文本已显示；如果记事本为空或文本不正确，回复 [NO]。"
        )
        sr.set_vision_result(vision["success"], vision["analysis"])
        sr.detail = f"已输入文本（剪贴板粘贴方式）"
        print(f"  👁️ 视觉判定: {'通过' if vision['success'] else '未通过'} — {vision['analysis'][:80]}")
        print(f"  {'✓' if sr.success else '✗'} Step 2 {'通过' if sr.success else '失败'}")
    except Exception as e:
        sr.finish(False, error=str(e))
        screenshot("step2_error")
        print(f"  ✗ Step 2 异常: {e}")

    results.append(sr)
    return sr


def step_3_save_file(results: list) -> StepResult:
    """Step 3: 保存文件到指定路径"""
    sr = StepResult("保存文件到指定路径")
    print(f"\n[Step 3] 保存文件到: {SAVE_FILE_PATH}")

    try:
        # 清理旧的测试文件
        if SAVE_FILE_PATH.exists():
            SAVE_FILE_PATH.unlink()

        # 确保记事本在前台
        bring_notepad_front()
        wait(WAIT_SHORT, "确保记事本在前台")

        # Ctrl+S 打开保存对话框
        pyautogui.hotkey("ctrl", "s")
        wait(WAIT_MEDIUM, "等待保存对话框")
        sr.screenshot_path = screenshot("step3_save_dialog")

        # 视觉验证：保存对话框是否出现
        vision_dialog = analyze_screenshot(
            str(sr.screenshot_path),
            "请判断屏幕上是否出现了'另存为'或'保存'对话框。"
            "如果是，回复 [YES] 保存对话框已出现；否则回复 [NO]。"
        )
        print(f"  👁️ 对话框检查: {'通过' if vision_dialog['success'] else '未通过'} — {vision_dialog['analysis'][:80]}")

        # 输入文件路径（剪贴板方式）
        # 先等待文件名输入框聚焦（保存对话框默认焦点在文件名输入框）
        wait(1, "等待文件名输入框聚焦")
        # 清空当前内容
        pyautogui.hotkey("ctrl", "a")
        wait(0.3)
        # 粘贴完整文件路径
        paste_text(str(SAVE_FILE_PATH))
        wait(WAIT_SHORT, "等待路径输入")
        sr.screenshot_path = screenshot("step3_path_entered")

        # 视觉验证：路径是否输入正确
        vision_path = analyze_screenshot(
            str(sr.screenshot_path),
            "请判断保存对话框的文件名输入框中是否包含文件路径（类似 C:\\...\\javasagent_notepad_test.txt）。"
            "如果是，回复 [YES] 路径已输入；否则回复 [NO]。"
        )
        print(f"  👁️ 路径检查: {'通过' if vision_path['success'] else '未通过'} — {vision_path['analysis'][:80]}")

        # 按回车确认保存
        pyautogui.press("enter")
        wait(WAIT_MEDIUM, "等待文件保存完成")

        # 处理可能出现的"确认替换"对话框
        # 如果文件已存在会弹出确认框，按左箭头+回车选"是"
        sr.screenshot_path = screenshot("step3_after_save")

        # 视觉验证：保存对话框是否已关闭
        vision_saved = analyze_screenshot(
            str(sr.screenshot_path),
            "请判断：1) 保存对话框是否已经关闭？2) 是否回到了记事本编辑界面？"
            "如果保存对话框已关闭且回到了编辑界面，回复 [YES] 已保存；"
            "如果还有对话框弹出或看起来保存未完成，回复 [NO]。"
        )
        sr.set_vision_result(vision_saved["success"], vision_saved["analysis"])
        sr.detail = f"保存到: {SAVE_FILE_PATH}"
        print(f"  👁️ 视觉判定: {'通过' if vision_saved['success'] else '未通过'} — {vision_saved['analysis'][:80]}")
        print(f"  {'✓' if sr.success else '✗'} Step 3 {'通过' if sr.success else '失败'}")
    except Exception as e:
        sr.finish(False, error=str(e))
        screenshot("step3_error")
        print(f"  ✗ Step 3 异常: {e}")

    results.append(sr)
    return sr


def step_4_verify_file(results: list) -> StepResult:
    """Step 4: 验证文件内容"""
    sr = StepResult("验证文件内容")
    print(f"\n[Step 4] 验证文件: {SAVE_FILE_PATH}")

    try:
        # 脚本验证：检查文件是否存在且内容匹配
        if SAVE_FILE_PATH.exists():
            content = SAVE_FILE_PATH.read_text(encoding="utf-8")
            script_ok = content.strip() == TEST_TEXT.strip()
            sr.script_success = script_ok
            sr.detail = f"文件存在，内容{'匹配' if script_ok else '不匹配'}"
            if script_ok:
                sr.finish(True, f"文件内容完全匹配")
            else:
                sr.finish(False, error=f"文件内容不匹配。期望:\n{TEST_TEXT}\n实际:\n{content}")
        else:
            sr.script_success = False
            sr.finish(False, error=f"文件不存在: {SAVE_FILE_PATH}")

        sr.screenshot_path = screenshot("step4_verify_state")

        # 视觉验证：记事本当前显示的文本是否正确
        vision = analyze_screenshot(
            str(sr.screenshot_path),
            "请判断记事本中显示的文本是否包含'JavasAgent端到端测试'和'Hello World'等内容。"
            "如果文本内容完整正确，回复 [YES] 文本内容匹配；否则回复 [NO]。"
        )
        sr.set_vision_result(vision["success"], vision["analysis"])
        print(f"  👁️ 视觉判定: {'通过' if vision['success'] else '未通过'} — {vision['analysis'][:80]}")
        print(f"  {'✓' if sr.success else '✗'} Step 4 {'通过' if sr.success else '失败'}")
    except Exception as e:
        sr.finish(False, error=str(e))
        screenshot("step4_error")
        print(f"  ✗ Step 4 异常: {e}")

    results.append(sr)
    return sr


def step_5_close_notepad(results: list) -> StepResult:
    """Step 5: 关闭记事本"""
    sr = StepResult("关闭记事本")
    print("\n[Step 5] 关闭记事本")

    try:
        # 确保记事本在前台
        bring_notepad_front()
        wait(WAIT_SHORT, "等待记事本获得焦点")
        pyautogui.hotkey("alt", "f4")
        wait(WAIT_SHORT, "等待记事本关闭")
        sr.screenshot_path = screenshot("step5_notepad_closed")

        # 视觉验证：记事本是否已关闭
        vision = analyze_screenshot(
            str(sr.screenshot_path),
            "请判断屏幕上是否还有记事本窗口。如果记事本已关闭（看不到记事本窗口），回复 [YES] 已关闭；否则回复 [NO]。"
        )
        sr.set_vision_result(vision["success"], vision["analysis"])
        sr.detail = "已发送 Alt+F4 关闭记事本"
        print(f"  👁️ 视觉判定: {'通过' if vision['success'] else '未通过'} — {vision['analysis'][:80]}")
        print(f"  {'✓' if sr.success else '✗'} Step 5 {'通过' if sr.success else '失败'}")
    except Exception as e:
        sr.finish(False, error=str(e))
        screenshot("step5_error")
        print(f"  ✗ Step 5 异常: {e}")

    results.append(sr)
    return sr


# ─── 主流程 ────────────────────────────────────────────
def run_test():
    """运行完整的记事本文本编辑端到端测试"""
    print("=" * 60)
    print("E2E Test: Notepad Text Edit Scenario")
    print(f"时间: {datetime.now().isoformat()}")
    print(f"屏幕: {SCREEN_W}×{SCREEN_H}")
    print(f"测试文本: {TEST_TEXT[:40]}...")
    print(f"保存路径: {SAVE_FILE_PATH}")
    print(f"Evidence 目录: {EVIDENCE_DIR}")
    print(f"视觉验证: Ollama {OLLAMA_MODEL} ({OLLAMA_URL})")
    print("=" * 60)

    results = []
    start_time = time.time()

    steps = [
        step_1_open_notepad,
        step_2_type_chinese,
        step_3_save_file,
        step_4_verify_file,
        step_5_close_notepad,
    ]

    for step_fn in steps:
        try:
            step_fn(results)
        except Exception as e:
            print(f"  ⚠ 步骤执行异常（继续）: {e}")
            sr = StepResult(step_fn.__name__)
            sr.finish(False, error=f"未捕获异常: {traceback.format_exc()}")
            results.append(sr)

    total_time = time.time() - start_time

    # 生成报告
    report = generate_report(results, total_time)
    report_path = EVIDENCE_DIR / "report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n📄 测试报告已保存: {report_path}")

    # 生成 Markdown 报告
    md_report = generate_markdown_report(results, total_time)
    md_path = EVIDENCE_DIR / "report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_report)
    print(f"📄 Markdown 报告已保存: {md_path}")

    # 打印摘要
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r.success)
    failed = len(results) - passed
    script_passed = sum(1 for r in results if r.script_success)
    vision_available = sum(1 for r in results if r.vision_success is not None)
    print(f"测试完成: {passed}/{len(results)} 最终通过, {failed} 失败")
    print(f"脚本判定: {script_passed}/{len(results)} 通过")
    print(f"视觉验证: {vision_available}/{len(results)} 可用")
    if failed > 0:
        print("\n失败分类:")
        for r in results:
            if not r.success:
                print(f"  - {r.step_name}: [{r.failure_category}] {r.error or r.vision_analysis[:60]}")
    print("=" * 60)

    return report


def generate_report(results: list, total_time: float) -> dict:
    """生成 JSON 测试报告"""
    passed = sum(1 for r in results if r.success)
    failed = len(results) - passed
    script_passed = sum(1 for r in results if r.script_success)
    vision_available = sum(1 for r in results if r.vision_success is not None)
    vision_passed = sum(1 for r in results if r.vision_success is True)

    failure_breakdown = {"PERCEPTION": 0, "LOCATION": 0, "OPERATION": 0, "DECISION": 0}
    for r in results:
        if not r.success and r.failure_category:
            failure_breakdown[r.failure_category] = failure_breakdown.get(r.failure_category, 0) + 1

    return {
        "test_name": "Notepad Text Edit E2E",
        "timestamp": datetime.now().isoformat(),
        "screen_resolution": f"{SCREEN_W}x{SCREEN_H}",
        "test_text": TEST_TEXT,
        "save_path": str(SAVE_FILE_PATH),
        "vision_model": OLLAMA_MODEL,
        "total_duration_sec": round(total_time, 2),
        "summary": {
            "total_steps": len(results),
            "script_passed": script_passed,
            "vision_available": vision_available,
            "vision_passed": vision_passed,
            "final_passed": passed,
            "final_failed": failed,
            "final_pass_rate": f"{passed/len(results)*100:.0f}%" if results else "N/A",
        },
        "failure_breakdown": failure_breakdown,
        "steps": [r.to_dict() for r in results],
        "note": "每步有脚本判定 + Ollama qwen3-vl 视觉判定，最终结果以视觉判定为准。",
    }


def generate_markdown_report(results: list, total_time: float) -> str:
    """生成 Markdown 测试报告"""
    passed = sum(1 for r in results if r.success)
    failed = len(results) - passed
    script_passed = sum(1 for r in results if r.script_success)
    vision_available = sum(1 for r in results if r.vision_success is not None)
    vision_passed = sum(1 for r in results if r.vision_success is True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# E2E Test Report: Notepad Text Edit",
        "",
        f"- **时间**: {now}",
        f"- **屏幕**: {SCREEN_W}×{SCREEN_H}",
        f"- **测试文本**: `{TEST_TEXT[:50]}...`",
        f"- **保存路径**: `{SAVE_FILE_PATH}`",
        f"- **视觉验证模型**: {OLLAMA_MODEL}",
        f"- **总耗时**: {total_time:.1f}s",
        "",
        "## 结果摘要",
        "",
        f"| 指标 | 值 |",
        f"|------|------|",
        f"| 总步骤 | {len(results)} |",
        f"| 脚本判定通过 | {script_passed} |",
        f"| 视觉验证可用 | {vision_available} |",
        f"| 视觉验证通过 | {vision_passed} |",
        f"| 最终通过 | {passed} |",
        f"| 最终失败 | {failed} |",
        f"| 实际通过率 | {passed/len(results)*100:.0f}% |",
        "",
        "## 脚本判定 vs 视觉判定对比",
        "",
        "| # | 步骤 | 脚本判定 | 视觉判定 | 最终结果 | 耗时 | 说明 |",
        "|---|------|----------|----------|----------|------|------|",
    ]

    for i, r in enumerate(results, 1):
        s_script = "✅" if r.script_success else "❌"
        s_vision = "✅" if r.vision_success is True else ("❌" if r.vision_success is False else "❓")
        s_final = "✅" if r.success else "❌"
        duration = f"{r.end_time - r.start_time:.1f}s" if r.end_time else "N/A"
        detail = r.detail if r.success else (r.error or r.vision_analysis or "")[:60].replace("|", "\\|")
        lines.append(
            f"| {i} | {r.step_name} | {s_script} | {s_vision} | {s_final} | {duration} | {detail} |"
        )

    # 失败分类
    failure_breakdown = {"PERCEPTION": 0, "LOCATION": 0, "OPERATION": 0, "DECISION": 0}
    for r in results:
        if not r.success and r.failure_category:
            failure_breakdown[r.failure_category] = failure_breakdown.get(r.failure_category, 0) + 1

    if failed > 0:
        lines.extend([
            "",
            "## 失败分类",
            "",
            "| 分类 | 数量 | 说明 |",
            "|------|------|------|",
            f"| PERCEPTION（感知失败） | {failure_breakdown['PERCEPTION']} | 无法识别屏幕状态 |",
            f"| LOCATION（定位失败） | {failure_breakdown['LOCATION']} | 无法找到目标元素位置 |",
            f"| OPERATION（操作失败） | {failure_breakdown['OPERATION']} | 操作执行了但效果不对 |",
            f"| DECISION（决策失败） | {failure_breakdown['DECISION']} | 策略或时序错误 |",
        ])

    # 视觉分析详情
    lines.extend(["", "## 视觉分析详情", ""])
    for i, r in enumerate(results, 1):
        lines.append(f"### Step {i}: {r.step_name}")
        if r.vision_analysis:
            lines.append(f"> {r.vision_analysis[:300]}")
        else:
            lines.append("> 无视觉分析结果")
        lines.append("")

    # 截图证据
    lines.extend(["", "## 截图证据", ""])
    for r in results:
        if r.screenshot_path:
            lines.append(f"- **{r.step_name}**: `{r.screenshot_path.name}`")

    lines.extend([
        "",
        "---",
        f"*本报告由 tests/e2e/test_notepad_edit.py 自动生成*",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    report = run_test()
    failed = report["summary"]["final_failed"]
    sys.exit(1 if failed > 0 else 0)
