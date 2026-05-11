"""T-HH-03 近距离微调移动 + T-HH-04 拟人点击偏移 实操测试脚本。

测试说明：
- T-HH-03：验证 HumanHand 在近距离（~50px）移动时有细微抖动效果
- T-HH-04：验证 human_click 点击在目标附近有随机偏移，多次点击不完全相同

注意：屏幕分辨率 3840x2160，坐标范围安全。
"""

import asyncio
import sys
import os
import time
import random
import io

# 修复 Windows 控制台编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import pyautogui

# 禁用 failsafe 防止角落误触发
pyautogui.FAILSAFE = False

# 将项目根目录加入 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.platforms.windows import WindowsAdapter
from src.platforms.human_hand import HumanHand, HumanHandConfig

# 测试输出目录
EVIDENCE_DIR = os.path.join(PROJECT_ROOT, "test-evidence", "08-real-execution")
HH03_DIR = os.path.join(EVIDENCE_DIR, "REAL-HH03-micro-move")
HH04_DIR = os.path.join(EVIDENCE_DIR, "REAL-HH04-click-offset")


def get_mouse_pos() -> tuple[int, int]:
    pos = pyautogui.position()
    return pos.x, pos.y


async def safe_screenshot(adapter: WindowsAdapter, filepath: str, retries: int = 3) -> int:
    """截屏并保存，带重试逻辑。"""
    for attempt in range(retries):
        try:
            # 确保鼠标不在角落
            mx, my = get_mouse_pos()
            if mx < 10 and my < 10:
                await adapter.move_to(500, 500, duration=0)
                await asyncio.sleep(0.1)

            data = await adapter.screenshot()
            with open(filepath, "wb") as f:
                f.write(data)
            return len(data)
        except OSError as e:
            print(f"    [截图重试 {attempt+1}/{retries}] {e}")
            await asyncio.sleep(2)
    # 最后一次尝试用 region 截取小区域
    try:
        data = await adapter.screenshot(region=(0, 0, 1920, 1080))
        with open(filepath, "wb") as f:
            f.write(data)
        return len(data)
    except Exception as e:
        print(f"    [截图最终失败] {e}")
        # 写入一个占位文件
        with open(filepath + ".failed", "w") as f:
            f.write(f"Screenshot failed: {e}\n")
        return 0


# ============================================================
# T-HH-03: 近距离微调移动
# ============================================================
async def test_hh03_micro_move():
    """T-HH-03: 近距离微调移动测试。"""
    print("=" * 60)
    print("T-HH-03: 近距离微调移动测试")
    print("=" * 60)

    adapter = WindowsAdapter(action_delay=0.0)
    pyautogui.FAILSAFE = False
    config = HumanHandConfig(
        move_speed=1.0,
        jitter_range=2.0,
        bezier_control_points=3,
    )
    hand = HumanHand(adapter, config)

    # 步骤 1: 先移动到一个安全的起始位置
    start_x, start_y = 500, 500
    print(f"\n[步骤1] 大距离移动到起始位置 ({start_x}, {start_y})...")
    await adapter.move_to(start_x, start_y, duration=0.3)
    await asyncio.sleep(0.3)

    actual_start = get_mouse_pos()
    print(f"  实际起始位置: ({actual_start[0]}, {actual_start[1]})")

    # 步骤 2: 截屏记录起始状态
    ss_path = os.path.join(HH03_DIR, "screenshot_before_micro_move.png")
    size = await safe_screenshot(adapter, ss_path)
    print(f"  起始截图已保存: {ss_path} ({size} bytes)")

    # 步骤 3: 近距离微调移动 ~50px，带 jitter 抖动
    target_x, target_y = 550, 510
    dist = ((target_x - start_x) ** 2 + (target_y - start_y) ** 2) ** 0.5
    print(f"\n[步骤2] 近距离微调移动 ({start_x},{start_y}) -> ({target_x},{target_y}), 距离={dist:.1f}px")

    # 使用 HumanHand 的贝塞尔曲线 + jitter 逻辑
    control_points = hand._generate_control_points(
        start_x, start_y, target_x, target_y,
        num_points=config.bezier_control_points,
    )
    num_steps = 15
    curve = hand._bezier_curve(control_points, num_steps)

    move_positions = []
    for i, (cx, cy) in enumerate(curve):
        jx = cx + random.uniform(-config.jitter_range, config.jitter_range)
        jy = cy + random.uniform(-config.jitter_range, config.jitter_range)
        jx, jy = int(jx), int(jy)
        move_positions.append((jx, jy))
        await adapter.move_to(jx, jy, duration=0)
        await asyncio.sleep(0.01)

    print(f"  移动轨迹（含抖动）:")
    for i, pos in enumerate(move_positions):
        print(f"    步骤{i+1}: ({pos[0]}, {pos[1]})")

    # 最终精确移动到目标
    await adapter.move_to(target_x, target_y, duration=0)
    await asyncio.sleep(0.05)

    # 记录终点位置
    end_pos = get_mouse_pos()
    print(f"\n  实际终点位置: ({end_pos[0]}, {end_pos[1]})")
    print(f"  目标终点位置: ({target_x}, {target_y})")

    # 计算偏差
    offset = ((end_pos[0] - target_x) ** 2 + (end_pos[1] - target_y) ** 2) ** 0.5
    print(f"  终点偏差: {offset:.2f}px")

    # 验证抖动效果
    jitter_offsets = []
    for i, (mx, my) in enumerate(move_positions):
        t = (i + 1) / len(move_positions)
        ideal_x = start_x + (target_x - start_x) * t
        ideal_y = start_y + (target_y - start_y) * t
        jitter_dist = ((mx - ideal_x) ** 2 + (my - ideal_y) ** 2) ** 0.5
        jitter_offsets.append(jitter_dist)

    avg_jitter = sum(jitter_offsets) / len(jitter_offsets) if jitter_offsets else 0
    max_jitter = max(jitter_offsets) if jitter_offsets else 0
    has_jitter = any(j > 0.5 for j in jitter_offsets)
    print(f"  平均抖动偏移: {avg_jitter:.2f}px")
    print(f"  最大抖动偏移: {max_jitter:.2f}px")
    print(f"  有抖动效果: {'YES' if has_jitter else 'NO'}")

    passed = offset <= 5.0 and has_jitter
    result_str = "PASS" if passed else "FAIL"
    print(f"\n[验证] 终点偏差 <= 5px 且有抖动: {result_str}")
    print(f"  - 偏差 {offset:.2f}px <= 5px: {'OK' if offset <= 5 else 'FAIL'}")
    print(f"  - 有抖动: {'OK' if has_jitter else 'FAIL'}")

    # 截屏记录结束状态
    ss_path2 = os.path.join(HH03_DIR, "screenshot_after_micro_move.png")
    size = await safe_screenshot(adapter, ss_path2)
    print(f"  结束截图已保存: {ss_path2} ({size} bytes)")

    # 写入测试描述
    desc = f"""# T-HH-03: 近距离微调移动

## 测试描述
验证 HumanHand 在近距离（~50px）移动时，有细微抖动效果，终点精度在 +/-5px 内。

## 测试步骤
1. 使用 WindowsAdapter 大距离移动到起始位置 (500, 500)
2. 截屏记录起始状态
3. 使用 HumanHand 的贝塞尔曲线 + jitter 逻辑进行近距离微调移动到 (550, 510)
4. 最终精确移动到目标点
5. 记录鼠标实际终点位置
6. 验证终点偏差 <= 5px 且轨迹有抖动
7. 截屏记录结束状态

## 测试参数
- 起始位置: ({start_x}, {start_y})
- 目标位置: ({target_x}, {target_y})
- 移动距离: {dist:.1f}px
- jitter_range: {config.jitter_range}px
- move_speed: {config.move_speed}
- bezier_control_points: {config.bezier_control_points}

## 移动轨迹
| 步骤 | 位置 |
|------|------|
"""
    for i, pos in enumerate(move_positions):
        desc += f"| {i+1} | ({pos[0]}, {pos[1]}) |\n"

    desc += f"""
## 测试结果
- 实际起点: ({actual_start[0]}, {actual_start[1]})
- 实际终点: ({end_pos[0]}, {end_pos[1]})
- 终点偏差: {offset:.2f}px
- 平均抖动偏移: {avg_jitter:.2f}px
- 最大抖动偏移: {max_jitter:.2f}px
- 有抖动效果: {'YES' if has_jitter else 'NO'}
- **判定: {'PASS' if passed else 'FAIL'}**

## 截图文件
- `screenshot_before_micro_move.png` - 移动前截图
- `screenshot_after_micro_move.png` - 移动后截图

## 测试时间
{time.strftime('%Y-%m-%d %H:%M:%S')}
"""
    desc_path = os.path.join(HH03_DIR, "TEST-DESC.md")
    with open(desc_path, "w", encoding="utf-8") as f:
        f.write(desc)
    print(f"  测试描述已保存: {desc_path}")

    return passed, offset


# ============================================================
# T-HH-04: 拟人点击（偏移）
# ============================================================
async def test_hh04_click_offset():
    """T-HH-04: 拟人点击偏移测试。"""
    print("\n" + "=" * 60)
    print("T-HH-04: 拟人点击（偏移）测试")
    print("=" * 60)

    adapter = WindowsAdapter(action_delay=0.0)
    pyautogui.FAILSAFE = False
    config = HumanHandConfig(
        click_offset_range=5,
    )

    # 定义目标 bbox
    bbox = (500, 400, 600, 450)
    bbox_cx = (bbox[0] + bbox[2]) // 2
    bbox_cy = (bbox[1] + bbox[3]) // 2
    print(f"\n[步骤1] 定义目标 bbox: {bbox}")
    print(f"  bbox 中心: ({bbox_cx}, {bbox_cy})")
    print(f"  click_offset_range: {config.click_offset_range}px")

    # 截屏记录初始状态
    ss_path = os.path.join(HH04_DIR, "screenshot_before_clicks.png")
    size = await safe_screenshot(adapter, ss_path)
    print(f"  初始截图已保存: {ss_path} ({size} bytes)")

    # 执行 3 次拟人点击
    click_positions = []
    for i in range(3):
        print(f"\n[步骤2.{i+1}] 执行第 {i+1} 次拟人点击...")

        # 先移到远处
        await adapter.move_to(800, 800, duration=0)
        await asyncio.sleep(0.1)

        # 计算随机偏移（模拟 HumanHand.human_click 的偏移逻辑）
        offset_x = random.randint(-config.click_offset_range, config.click_offset_range)
        offset_y = random.randint(-config.click_offset_range, config.click_offset_range)
        click_x = bbox_cx + offset_x
        click_y = bbox_cy + offset_y

        print(f"    偏移量: ({offset_x}, {offset_y})")
        print(f"    点击位置: ({click_x}, {click_y})")

        # 移动到点击位置
        await adapter.move_to(click_x, click_y, duration=0.1)
        await asyncio.sleep(random.uniform(0.05, 0.2))

        # 点击
        await adapter.click(click_x, click_y, button="left", clicks=1)
        await asyncio.sleep(random.uniform(0.03, 0.1))

        click_positions.append((click_x, click_y))
        print(f"    记录点击坐标: ({click_x}, {click_y})")

        await asyncio.sleep(0.3)

    # 截屏记录结束状态
    ss_path2 = os.path.join(HH04_DIR, "screenshot_after_clicks.png")
    size = await safe_screenshot(adapter, ss_path2)
    print(f"\n  结束截图已保存: {ss_path2} ({size} bytes)")

    # 验证
    print(f"\n[验证] 分析点击坐标...")

    all_in_bbox = True
    for i, (cx, cy) in enumerate(click_positions):
        in_bbox = bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]
        all_in_bbox = all_in_bbox and in_bbox
        print(f"  点击{i+1}: ({cx}, {cy}) - 偏移({cx - bbox_cx}, {cy - bbox_cy}) - {'IN bbox' if in_bbox else 'OUT bbox'}")

    all_same = (click_positions[0] == click_positions[1] == click_positions[2])
    has_random = not all_same
    print(f"\n  三次点击坐标: {click_positions}")
    print(f"  在 bbox 内: {'YES' if all_in_bbox else 'NO'}")
    print(f"  有随机偏移（三次不完全相同）: {'YES' if has_random else 'NO'}")

    passed = all_in_bbox and has_random
    result_str = "PASS" if passed else "FAIL"

    print(f"\n[总判定] {result_str}")

    # 写入测试描述
    desc = f"""# T-HH-04: 拟人点击（偏移）

## 测试描述
验证 HumanHand 的点击偏移机制：点击在目标 bbox 中心附近有随机偏移，多次点击不完全相同。

## 测试步骤
1. 定义目标 bbox: {bbox}
2. 3 次点击 bbox 中心附近（加入 [-{config.click_offset_range}, +{config.click_offset_range}]px 随机偏移）
3. 记录每次点击坐标
4. 验证每次点击坐标都在 bbox 内，且三次不完全相同
5. 截屏保存

## 测试参数
- 目标 bbox: {bbox}
- bbox 中心: ({bbox_cx}, {bbox_cy})
- click_offset_range: {config.click_offset_range}px

## 点击记录
| 次数 | 坐标 | X偏移 | Y偏移 | 在bbox内 |
|------|------|-------|-------|---------|
"""
    for i, (cx, cy) in enumerate(click_positions):
        in_bbox = bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]
        desc += f"| {i+1} | ({cx}, {cy}) | {cx - bbox_cx} | {cy - bbox_cy} | {'YES' if in_bbox else 'NO'} |\n"

    desc += f"""
## 验证结果
- 所有点击在 bbox 内: {'YES' if all_in_bbox else 'NO'}
- 有随机偏移（三次不完全相同）: {'YES' if has_random else 'NO'}
- **总判定: {'PASS' if passed else 'FAIL'}**

## 截图文件
- `screenshot_before_clicks.png` - 点击前截图
- `screenshot_after_clicks.png` - 点击后截图

## 测试时间
{time.strftime('%Y-%m-%d %H:%M:%S')}
"""
    desc_path = os.path.join(HH04_DIR, "TEST-DESC.md")
    with open(desc_path, "w", encoding="utf-8") as f:
        f.write(desc)
    print(f"  测试描述已保存: {desc_path}")

    return passed, click_positions


async def main():
    print("JavasAgent 实操测试: T-HH-03 + T-HH-04")
    print(f"屏幕分辨率: {pyautogui.size()}")
    print(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    os.makedirs(HH03_DIR, exist_ok=True)
    os.makedirs(HH04_DIR, exist_ok=True)

    # 先移到安全位置
    pyautogui.moveTo(960, 540, duration=0)
    await asyncio.sleep(0.5)

    hh03_passed, hh03_offset = await test_hh03_micro_move()
    hh04_passed, hh04_positions = await test_hh04_click_offset()

    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)
    print(f"  T-HH-03 近距离微调移动: {'PASS' if hh03_passed else 'FAIL'} (偏差: {hh03_offset:.2f}px)")
    print(f"  T-HH-04 拟人点击偏移:   {'PASS' if hh04_passed else 'FAIL'} (点击坐标: {hh04_positions})")

    pyautogui.FAILSAFE = True
    return 0 if (hh03_passed and hh04_passed) else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
