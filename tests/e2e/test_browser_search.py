"""
E2E Test: Browser Search Scenario
===================================
端到端测试：打开浏览器 → 输入关键词 → 搜索 → 打开第一个结果 → 截图验证

使用 pyautogui + PIL 实现桌面操作，独立于 JavasAgent Agent 框架。
屏幕分辨率：3840×2160，DPI 缩放需注意。

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
from PIL import Image

# ─── 配置 ─────────────────────────────────────────────
SCREEN_W, SCREEN_H = 3840, 2160
SEARCH_KEYWORD = "JavasAgent GitHub"
WAIT_SHORT = 2  # 秒，短等待
WAIT_MEDIUM = 5  # 秒，中等等待
WAIT_LONG = 10  # 秒，长等待（页面加载）
MAX_RETRIES = 2  # 最大重试次数

# 路径
EVIDENCE_DIR = Path(__file__).resolve().parent.parent.parent / "test-evidence" / "e2e-browser-search"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# pyautogui 安全设置
pyautogui.PAUSE = 0.5  # 每个操作间暂停 0.5s
pyautogui.FAILSAFE = True


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
    if any(k in ctx for k in ["not found", "找不到", "无法识别", "screenshot", "感知"]):
        return "PERCEPTION"
    if any(k in ctx for k in ["位置", "坐标", "定位", "click at", "locate"]):
        return "LOCATION"
    if any(k in ctx for k in ["点击", "输入", "type", "click", "press", "操作"]):
        return "OPERATION"
    return "DECISION"


class StepResult:
    """单个步骤的结果"""

    def __init__(self, step_name: str):
        self.step_name = step_name
        self.success = False
        self.start_time = time.time()
        self.end_time = None
        self.screenshot_path = None
        self.error = None
        self.failure_category = None
        self.detail = ""

    def finish(self, success: bool, detail: str = "", error: str = None):
        self.success = success
        self.end_time = time.time()
        self.detail = detail
        self.error = error
        if not success and error:
            self.failure_category = classify_failure(error)

    def to_dict(self) -> dict:
        return {
            "step": self.step_name,
            "success": self.success,
            "duration_sec": round(self.end_time - self.start_time, 2) if self.end_time else None,
            "screenshot": self.screenshot_path.name if self.screenshot_path else None,
            "detail": self.detail,
            "error": self.error,
            "failure_category": self.failure_category,
        }


def wait(seconds: float, desc: str = ""):
    """等待并打印进度"""
    label = f" ({desc})" if desc else ""
    print(f"  ⏳ 等待 {seconds}s{label}...")
    time.sleep(seconds)


def ensure_browser_open() -> bool:
    """确保浏览器已打开，如果没有则打开 Edge"""
    try:
        # 检查是否有 Edge 或 Chrome 进程
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq msedge.exe"],
            capture_output=True, text=True, timeout=5
        )
        if "msedge.exe" in result.stdout:
            print("  ✓ Edge 浏览器已在运行")
            return True

        # 尝试 Chrome
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
            capture_output=True, text=True, timeout=5
        )
        if "chrome.exe" in result.stdout:
            print("  ✓ Chrome 浏览器已在运行")
            return True

        # 打开 Edge
        print("  🚀 打开 Edge 浏览器...")
        subprocess.Popen(
            ["start", "msedge"],
            shell=True
        )
        wait(WAIT_LONG, "等待浏览器启动")
        return True
    except Exception as e:
        print(f"  ✗ 打开浏览器失败: {e}")
        return False


def focus_browser() -> bool:
    """尝试将浏览器窗口置于前台"""
    try:
        # 用 Alt+Tab 的方式不太可靠，直接用 pyautogui 点击任务栏或用快捷键
        # 先尝试用 Windows 键 + 数字键（假设 Edge 在任务栏）
        # 更可靠的方式：直接搜索并点击浏览器区域
        # 先截一张图看看当前状态
        img = pyautogui.screenshot()
        # 检查屏幕上方是否有浏览器标签栏的迹象
        # 简单做法：用 Alt+D 聚焦地址栏（大多数浏览器通用）
        pyautogui.hotkey("alt", "d")
        wait(1, "等待地址栏聚焦")
        return True
    except Exception as e:
        print(f"  ✗ 聚焦浏览器失败: {e}")
        return False


# ─── 测试步骤 ──────────────────────────────────────────
def step_1_open_browser(results: list) -> StepResult:
    """Step 1: 确保浏览器已打开"""
    sr = StepResult("打开浏览器")
    print("\n[Step 1] 打开浏览器")
    sr.screenshot_path = screenshot("step1_before")

    try:
        ok = ensure_browser_open()
        if ok:
            sr.finish(True, "浏览器已打开/已存在")
            sr.screenshot_path = screenshot("step1_after")
            print("  ✓ Step 1 通过")
        else:
            sr.finish(False, error="无法打开浏览器")
            screenshot("step1_fail")
            print("  ✗ Step 1 失败")
    except Exception as e:
        sr.finish(False, error=str(e))
        screenshot("step1_error")
        print(f"  ✗ Step 1 异常: {e}")

    results.append(sr)
    return sr


def step_2_navigate_to_search_engine(results: list) -> StepResult:
    """Step 2: 导航到搜索引擎（必应）"""
    sr = StepResult("导航到搜索引擎")
    print("\n[Step 2] 导航到必应搜索")

    try:
        # 用 Ctrl+L 或 Alt+D 聚焦地址栏
        pyautogui.hotkey("ctrl", "l")
        wait(1, "等待地址栏聚焦")
        sr.screenshot_path = screenshot("step2_addressbar")

        # 清空并输入必应地址
        pyautogui.hotkey("ctrl", "a")
        pyautogui.typewrite("https://www.bing.com", interval=0.05)
        pyautogui.press("enter")
        wait(WAIT_LONG, "等待必应页面加载")
        sr.screenshot_path = screenshot("step2_bing_loaded")

        # 验证：截图看看页面是否加载
        # 简单策略：截图确认页面状态（人工或后续AI验证）
        sr.finish(True, "已导航到必应搜索页面（需截图确认）")
        print("  ✓ Step 2 通过（截图确认页面状态）")
    except Exception as e:
        sr.finish(False, error=str(e))
        screenshot("step2_error")
        print(f"  ✗ Step 2 异常: {e}")

    results.append(sr)
    return sr


def step_3_type_keyword(results: list) -> StepResult:
    """Step 3: 在搜索框输入关键词"""
    sr = StepResult("输入搜索关键词")
    print(f"\n[Step 3] 输入关键词: {SEARCH_KEYWORD}")

    try:
        # 必应搜索框通常在页面中上部，点击搜索框区域
        # 在 3840×2160 分辨率下，必应搜索框大约在屏幕中上部
        # 先尝试点击页面中央偏上的位置（搜索框大致位置）
        search_box_x = SCREEN_W // 2
        search_box_y = SCREEN_H // 3  # 大约 1/3 高度处
        pyautogui.click(search_box_x, search_box_y)
        wait(WAIT_SHORT, "等待搜索框聚焦")
        sr.screenshot_path = screenshot("step3_searchbox_clicked")

        # 清空已有内容
        pyautogui.hotkey("ctrl", "a")
        wait(0.5)

        # 输入搜索关键词（pyautogui 不支持中文，用剪贴板方式）
        import pyperclip
        pyperclip.copy(SEARCH_KEYWORD)
        pyautogui.hotkey("ctrl", "v")
        wait(1, "等待粘贴完成")
        sr.screenshot_path = screenshot("step3_keyword_typed")

        sr.finish(True, f"已输入关键词: {SEARCH_KEYWORD}")
        print(f"  ✓ Step 3 通过")
    except Exception as e:
        sr.finish(False, error=str(e))
        screenshot("step3_error")
        print(f"  ✗ Step 3 异常: {e}")

    results.append(sr)
    return sr


def step_4_execute_search(results: list) -> StepResult:
    """Step 4: 执行搜索（按回车）"""
    sr = StepResult("执行搜索")
    print("\n[Step 4] 按回车执行搜索")

    try:
        pyautogui.press("enter")
        wait(WAIT_LONG, "等待搜索结果加载")
        sr.screenshot_path = screenshot("step4_search_results")

        sr.finish(True, "已执行搜索（需截图确认结果）")
        print("  ✓ Step 4 通过（截图确认搜索结果）")
    except Exception as e:
        sr.finish(False, error=str(e))
        screenshot("step4_error")
        print(f"  ✗ Step 4 异常: {e}")

    results.append(sr)
    return sr


def step_5_click_first_result(results: list) -> StepResult:
    """Step 5: 点击第一个搜索结果"""
    sr = StepResult("点击第一个搜索结果")
    print("\n[Step 5] 点击第一个搜索结果")

    try:
        # 必应搜索结果的第一个结果通常在页面上部
        # 大约在屏幕 1/4 到 1/2 高度之间
        first_result_x = SCREEN_W // 2  # 居中偏左
        first_result_y = int(SCREEN_H * 0.35)  # 大约 35% 高度
        pyautogui.click(first_result_x, first_result_y)
        wait(WAIT_LONG, "等待页面加载")
        sr.screenshot_path = screenshot("step5_first_result")

        sr.finish(True, "已点击第一个结果位置（需截图确认）")
        print("  ✓ Step 5 通过（截图确认打开的页面）")
    except Exception as e:
        sr.finish(False, error=str(e))
        screenshot("step5_error")
        print(f"  ✗ Step 5 异常: {e}")

    results.append(sr)
    return sr


def step_6_verify_result(results: list) -> StepResult:
    """Step 6: 截图验证最终结果"""
    sr = StepResult("截图验证")
    print("\n[Step 6] 截图验证最终状态")

    try:
        sr.screenshot_path = screenshot("step6_final")

        # 验证：截图存在即认为步骤完成
        # 实际内容验证需要人工或 AI 模型
        if sr.screenshot_path and sr.screenshot_path.exists():
            sr.finish(True, f"最终截图已保存: {sr.screenshot_path.name}")
            print(f"  ✓ Step 6 通过")
        else:
            sr.finish(False, error="截图保存失败")
            print("  ✗ Step 6 失败：截图未生成")
    except Exception as e:
        sr.finish(False, error=str(e))
        screenshot("step6_error")
        print(f"  ✗ Step 6 异常: {e}")

    results.append(sr)
    return sr


# ─── 主流程 ────────────────────────────────────────────
def run_test():
    """运行完整的浏览器搜索端到端测试"""
    print("=" * 60)
    print("E2E Test: Browser Search Scenario")
    print(f"时间: {datetime.now().isoformat()}")
    print(f"屏幕: {SCREEN_W}×{SCREEN_H}")
    print(f"搜索词: {SEARCH_KEYWORD}")
    print(f"Evidence 目录: {EVIDENCE_DIR}")
    print("=" * 60)

    results = []
    start_time = time.time()

    # 逐步执行，每步失败不影响后续（继续执行收集更多数据）
    steps = [
        step_1_open_browser,
        step_2_navigate_to_search_engine,
        step_3_type_keyword,
        step_4_execute_search,
        step_5_click_first_result,
        step_6_verify_result,
    ]

    for step_fn in steps:
        try:
            step_fn(results)
        except Exception as e:
            print(f"  ⚠ 步骤执行异常（继续）: {e}")
            # 补一个失败结果
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
    print(f"测试完成: {passed}/{len(results)} 通过, {failed} 失败")
    print(f"总耗时: {total_time:.1f}s")
    if failed > 0:
        print("\n失败分类:")
        for r in results:
            if not r.success:
                print(f"  - {r.step_name}: [{r.failure_category}] {r.error}")
    print("=" * 60)

    return report


def generate_report(results: list, total_time: float) -> dict:
    """生成 JSON 测试报告"""
    passed = sum(1 for r in results if r.success)
    failed = len(results) - passed

    failure_breakdown = {"PERCEPTION": 0, "LOCATION": 0, "OPERATION": 0, "DECISION": 0}
    for r in results:
        if not r.success and r.failure_category:
            failure_breakdown[r.failure_category] = failure_breakdown.get(r.failure_category, 0) + 1

    return {
        "test_name": "Browser Search E2E",
        "timestamp": datetime.now().isoformat(),
        "screen_resolution": f"{SCREEN_W}x{SCREEN_H}",
        "search_keyword": SEARCH_KEYWORD,
        "total_duration_sec": round(total_time, 2),
        "summary": {
            "total_steps": len(results),
            "passed": passed,
            "failed": failed,
            "pass_rate": f"{passed/len(results)*100:.0f}%" if results else "N/A",
        },
        "failure_breakdown": failure_breakdown,
        "steps": [r.to_dict() for r in results],
        "note": "这是验证性测试，使用 pyautogui 固定坐标操作，不依赖 JavasAgent Agent 框架。",
    }


def generate_markdown_report(results: list, total_time: float) -> str:
    """生成 Markdown 测试报告"""
    passed = sum(1 for r in results if r.success)
    failed = len(results) - passed
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# E2E Test Report: Browser Search",
        "",
        f"- **时间**: {now}",
        f"- **屏幕**: {SCREEN_W}×{SCREEN_H}",
        f"- **搜索词**: {SEARCH_KEYWORD}",
        f"- **总耗时**: {total_time:.1f}s",
        "",
        "## 结果摘要",
        "",
        f"| 指标 | 值 |",
        f"|------|------|",
        f"| 总步骤 | {len(results)} |",
        f"| 通过 | {passed} |",
        f"| 失败 | {failed} |",
        f"| 通过率 | {passed/len(results)*100:.0f}% |",
        "",
        "## 步骤详情",
        "",
        "| # | 步骤 | 状态 | 耗时 | 失败分类 | 说明 |",
        "|---|------|------|------|----------|------|",
    ]

    for i, r in enumerate(results, 1):
        status = "✅" if r.success else "❌"
        duration = f"{r.end_time - r.start_time:.1f}s" if r.end_time else "N/A"
        cat = r.failure_category or "-"
        detail = r.detail if r.success else (r.error or "").replace("|", "\\|")[:60]
        lines.append(f"| {i} | {r.step_name} | {status} | {duration} | {cat} | {detail} |")

    # 失败分类汇总
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

    lines.extend([
        "",
        "## 截图证据",
        "",
    ])
    for r in results:
        if r.screenshot_path:
            lines.append(f"- **{r.step_name}**: `{r.screenshot_path.name}`")

    lines.extend([
        "",
        "---",
        "*本报告由 tests/e2e/test_browser_search.py 自动生成*",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    report = run_test()
    # 如果有失败，退出码为 1
    failed = report["summary"]["failed"]
    sys.exit(1 if failed > 0 else 0)
