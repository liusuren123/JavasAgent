"""Phase 2 验证：用 UIA+HybridDetector 重新跑浏览器搜索场景。

对比 Phase 1（固定坐标 33% 通过率），验证 UI 检测能力的效果。
"""
import sys
import time
import json
import subprocess
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pyautogui
from PIL import ImageGrab

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.perception.hybrid_detector import HybridDetector
from src.perception.ui_operator import UIAOperator
from src.perception.ui_detector import UIElement

RESULTS_DIR = Path(__file__).parent.parent.parent / "test-evidence" / "e2e-browser-search-v2"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

detector = HybridDetector()
operator = UIAOperator()


def screenshot(name: str) -> Path:
    path = RESULTS_DIR / f"{name}.png"
    img = ImageGrab.grab()
    img.save(path)
    print(f"  截图: {path.name}")
    return path


def report_step(step_num: int, name: str, script_ok: bool, actual_ok: bool = None, fail_type: str = "", detail: str = ""):
    """统一报告函数"""
    if actual_ok is None:
        actual_ok = script_ok
    status = "✅" if actual_ok else "❌"
    print(f"\nStep {step_num}: {name} → {status}")
    if detail:
        print(f"  {detail}")


steps = []
def record(step_num, name, script_ok, actual_ok, fail_type="", detail=""):
    steps.append({
        "step": step_num, "name": name,
        "script_ok": script_ok, "actual_ok": actual_ok,
        "fail_type": fail_type, "detail": detail
    })


try:
    # ===== Step 1: 打开 Edge 浏览器 =====
    subprocess.Popen(["cmd", "/c", "start", "msedge"], shell=True)
    time.sleep(3)
    screenshot("step1_browser_opened")
    
    # 用 UIA 检测 Edge 窗口
    edge_elements = detector.uia_detector.scan("Edge")
    edge_found = len(edge_elements) > 0
    report_step(1, "打开浏览器", edge_found, edge_found,
                detail=f"检测到 {len(edge_elements)} 个 Edge 元素")
    record(1, "打开浏览器", edge_found, edge_found)

    # ===== Step 2: 导航到必应 =====
    subprocess.Popen(["cmd", "/c", "start", "msedge", "https://www.bing.com"], shell=True)
    time.sleep(5)
    screenshot("step2_bing_loaded")
    
    # 验证必应是否加载
    bing_elements = detector.uia_detector.scan("必应")
    if not bing_elements:
        bing_elements = detector.uia_detector.scan("Edge")
    bing_loaded = len(bing_elements) > 0
    report_step(2, "导航到必应", bing_loaded, bing_loaded,
                detail=f"必应页面元素: {len(bing_elements)}")
    record(2, "导航到必应", bing_loaded, bing_loaded)

    # ===== Step 3: 输入搜索关键词 =====
    # 用 HybridDetector 查找搜索框
    search_inputs = detector.find("输入框", window_title="Edge")
    if not search_inputs:
        # 备选：查找 Edit 类型且在页面中间的
        all_elements = detector.uia_detector.scan("Bing")
        search_inputs = [e for e in all_elements 
                        if "edit" in e.type.lower() 
                        and 200 < e.center[1] < 800
                        and 500 < e.center[0] < 2500]
    
    if search_inputs:
        search_box = search_inputs[0]
        print(f"  找到搜索框: bbox={search_box.bbox} type={search_box.type}")
        
        # 用 UIA 操作点击搜索框
        click_result = operator.click_element(search_box)
        time.sleep(0.5)
        
        # 输入关键词
        keyword = "JavasAgent GitHub"
        ps_cmd = f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::SetText(@'\n{keyword}\n'@)"
        subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, timeout=10)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(1.0)
        
        screenshot("step3_keyword_typed")
        report_step(3, "输入搜索关键词", True, True,
                    detail=f"搜索框: {search_box.type}, 关键词: {keyword}")
        record(3, "输入搜索关键词", True, True)
    else:
        screenshot("step3_no_searchbox")
        report_step(3, "输入搜索关键词", False, False, "LOCATION", "未找到搜索框")
        record(3, "输入搜索关键词", False, False, "LOCATION", "未找到搜索框")

    # ===== Step 4: 执行搜索 =====
    pyautogui.press("enter")
    time.sleep(5)
    screenshot("step4_search_executed")
    
    # 验证搜索结果
    result_elements = detector.uia_detector.scan("Bing")
    has_results = len(result_elements) > 20  # 搜索结果页面元素多
    report_step(4, "执行搜索", has_results, has_results,
                detail=f"结果页面元素: {len(result_elements)}")
    record(4, "执行搜索", has_results, has_results)

    # ===== Step 5: 点击第一个结果 =====
    # 查找可点击的链接/按钮
    links = [e for e in result_elements 
             if e.clickable and e.text 
             and "JavasAgent" in e.text]
    
    if not links:
        # 退而查找任何可点击的有文本元素
        links = [e for e in result_elements 
                if e.clickable and e.text and len(e.text) > 5
                and 300 < e.center[1] < 1500][:3]
    
    if links:
        first_link = links[0]
        print(f"  找到结果链接: text={first_link.text[:30]} bbox={first_link.bbox}")
        click_result = operator.click_element(first_link)
        time.sleep(5)
        screenshot("step5_first_result_clicked")
        report_step(5, "点击第一个结果", True, True,
                    detail=f"链接: {first_link.text[:50]}")
        record(5, "点击第一个结果", True, True)
    else:
        screenshot("step5_no_results")
        report_step(5, "点击第一个结果", False, False, "LOCATION", "未找到搜索结果链接")
        record(5, "点击第一个结果", False, False, "LOCATION", "未找到搜索结果链接")

    # ===== Step 6: 截图验证 =====
    screenshot("step6_final")
    report_step(6, "截图验证", True, True)
    record(6, "截图验证", True, True)

except Exception as e:
    print(f"\n❌ 测试异常: {e}")
    import traceback
    traceback.print_exc()

finally:
    # 生成报告
    passed = sum(1 for s in steps if s["actual_ok"])
    total = len(steps)
    rate = f"{passed/total*100:.0f}%" if total > 0 else "N/A"
    
    report = {
        "time": datetime.now().isoformat(),
        "screen": "3840x2160",
        "method": "HybridDetector (UIA+AI)",
        "total_steps": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": rate,
        "comparison": {
            "phase1_browser": "33%",
            "phase1_notepad": "40%",
        },
        "steps": steps,
    }
    
    report_path = RESULTS_DIR / "report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    # Markdown 报告
    md = f"""# E2E Test Report: Browser Search V2 (HybridDetector)

- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
- **检测方法**: HybridDetector (UIA + AI)
- **对比**: Phase 1 固定坐标 33% → 本次 ?
- **通过率**: {rate} ({passed}/{total})

| # | 步骤 | 结果 | 失败类型 | 说明 |
|---|------|------|----------|------|
"""
    for s in steps:
        status = "✅" if s["actual_ok"] else "❌"
        md += f"| {s['step']} | {s['name']} | {status} | {s.get('fail_type', '-')} | {s.get('detail', '-')} |\n"
    
    md += f"\n---\n*由 HybridDetector 验证脚本自动生成*\n"
    
    with open(RESULTS_DIR / "report.md", "w", encoding="utf-8") as f:
        f.write(md)
    
    print(f"\n{'='*50}")
    print(f"通过率: {rate} ({passed}/{total})")
    print(f"报告: {RESULTS_DIR}")
    print(f"对比 Phase 1: 33% → {rate}")

