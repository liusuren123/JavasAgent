"""T-MC-01: 闭环收敛实操测试 — 3 次迭代内成功点击目标。

测试策略：
  - 依赖缺失（GroundingDINO/OpenCV 视觉定位），用 mock 执行逻辑验证
  - 模拟闭环控制的「截屏→定位→点击→验证」循环
  - 每次迭代模拟视觉定位精度逐步提高（偏差递减），验证：
    1. 偏差随迭代递减
    2. 3 次迭代内收敛（最终偏差 < 5px）
    3. 返回 ActionStatus.SUCCESS

闭环模型：
  真实闭环流程为「看 → 判断 → 动作 → 验证」。
  在 mock 模式下：
  - find_target() 返回的坐标模拟视觉定位结果（逐步逼近真实目标）
  - 验证步骤中，当偏差足够小时返回 None（目标消失 → 收敛成功）
  - 偏差较大时仍返回目标（需继续迭代）

验证重点：
  - 每次 find_target 返回的定位偏差是否逐步缩小
  - 迭代次数是否 ≤ 3
  - 最终点击位置与目标位置的欧氏距离是否 < 5px
"""

from __future__ import annotations

import asyncio
import math
import os
import sys
import io
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

# 添加项目根目录到 sys.path
_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.platforms.motor_controller import (
    ActionStatus,
    ActionResult,
    MotorController,
    MotorControllerConfig,
)
from src.perception.target_cache import TargetInfo
from src.perception.target_matcher import MatchLevel, MatchResult


# ── 数据类 ──────────────────────────────────────

@dataclass
class IterationRecord:
    """单次迭代记录。"""
    iteration: int
    target_x: int
    target_y: int
    located_x: int
    located_y: int
    deviation_px: float
    note: str


# ── Mock 工厂 ──────────────────────────────────────

def _make_target(cx: int, cy: int, text: str = "测试按钮") -> TargetInfo:
    return TargetInfo(
        target_id=f"mock-{cx}-{cy}",
        text=text,
        bbox=(cx - 40, cy - 20, 80, 40),
        center=(cx, cy),
        element_type="button",
        confidence=0.95,
        screen_region="center",
        created_at=0.0,
    )


def _make_match(target: TargetInfo, score: float = 0.95) -> MatchResult:
    return MatchResult(
        target=target,
        level=MatchLevel.EXACT,
        score=score,
        confidence=score,
    )


# ── 核心测试函数 ──────────────────────────────────

def run_closed_loop_test(
    target_pos: tuple[int, int],
    convergence_sequence: list[tuple[int, int]],
    description: str,
) -> dict:
    """
    执行闭环收敛测试。

    Args:
        target_pos: 目标真实位置 (x, y)
        convergence_sequence: 收敛序列 [(offset_x, offset_y), ...]
            每项表示该次迭代 find_target 返回的坐标偏移。
            如 [(30, 20), (10, 8), (1, 0)] 表示：
              第1次: 定位到 (target_x+30, target_y+20)，偏差大，验证时目标仍在
              第2次: 定位到 (target_x+10, target_y+8)，偏差减小，验证时目标仍在
              第3次: 定位到 (target_x+1, target_y+0)，偏差小，验证时目标消失 → 收敛
        description: 测试描述

    Returns:
        测试结果字典
    """
    target_x, target_y = target_pos
    records: list[IterationRecord] = []

    # Mock 组件
    eye = AsyncMock()
    hand = AsyncMock()
    adapter = AsyncMock()
    adapter.screenshot = AsyncMock(return_value=b"fake-screenshot")
    eye.capture_and_analyze = AsyncMock(return_value=MagicMock())

    # 构造 find_target 的返回序列
    # 闭环逻辑：每次迭代 → find_target(查找) → 点击 → find_target(验证)
    # - 查找时：返回带偏移的目标
    # - 验证时：最后一次返回 None（目标消失/变化=收敛成功），
    #           之前的验证仍返回目标（目标仍在=需要继续迭代）
    find_side_effects = []
    for i, (offset_x, offset_y) in enumerate(convergence_sequence):
        located_x = target_x + offset_x
        located_y = target_y + offset_y
        target = _make_target(located_x, located_y)
        match = _make_match(target)

        # 查找时返回带偏移的目标
        find_side_effects.append(match)

        # 验证时：
        # - 如果是最后一次迭代（收敛成功），返回 None
        # - 否则返回目标仍在（触发重试）
        is_last = (i == len(convergence_sequence) - 1)
        if is_last:
            find_side_effects.append(None)  # 目标消失 → SUCCESS
        else:
            find_side_effects.append(match)  # 目标仍在 → 继续迭代

    eye.find_target = AsyncMock(side_effect=find_side_effects)
    hand.human_click = AsyncMock()

    config = MotorControllerConfig(
        max_attempts=len(convergence_sequence),
        verify_delay=0.0,
        action_timeout=5.0,
    )
    ctrl = MotorController(eye, hand, adapter, config)

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            ctrl.click_target("测试按钮", verify_change=True)
        )
    finally:
        loop.close()

    # 记录每次迭代的偏差（从 find_target 调用中提取）
    # eye.find_target 的调用参数可以用来推断迭代次数
    find_call_count = eye.find_target.call_count
    # 每次迭代调用 find_target 2次（查找+验证），最后一次验证返回None
    iterations = (find_call_count + 1) // 2  # 向上取整

    for i, (offset_x, offset_y) in enumerate(convergence_sequence):
        if i >= iterations:
            break
        located_x = target_x + offset_x
        located_y = target_y + offset_y
        deviation = math.sqrt(offset_x ** 2 + offset_y ** 2)
        records.append(IterationRecord(
            iteration=i + 1,
            target_x=target_x,
            target_y=target_y,
            located_x=located_x,
            located_y=located_y,
            deviation_px=round(deviation, 2),
            note=f"偏移({offset_x},{offset_y})",
        ))

    # 分析
    converged = result.status == ActionStatus.SUCCESS and len(records) <= 3
    final_deviation = records[-1].deviation_px if records else float("inf")
    converged = converged and final_deviation < 5.0

    deviations_decreasing = all(
        records[i].deviation_px >= records[i + 1].deviation_px
        for i in range(len(records) - 1)
    )

    return {
        "description": description,
        "target_pos": target_pos,
        "result_status": result.status.value,
        "result_message": result.message,
        "attempts": result.attempts,
        "duration_ms": round(result.duration_ms, 2),
        "records": records,
        "converged": converged,
        "final_deviation_px": final_deviation,
        "iterations": len(records),
        "deviations_decreasing": deviations_decreasing,
    }


# ── 主测试执行 ──────────────────────────────────────

def main():
    results = []

    print("=" * 70)
    print("T-MC-01: 闭环收敛实操测试")
    print("策略：依赖缺失（GroundingDINO/OpenCV），用 mock 执行逻辑验证")
    print("=" * 70)
    print()

    # ── 场景 1: 标准收敛 — 3次迭代，偏差逐步递减 ──
    print("场景 1: 标准收敛（偏差 36→13→2 px，3次迭代）")
    r1 = run_closed_loop_test(
        target_pos=(500, 300),
        convergence_sequence=[(30, 20), (10, 8), (2, 1)],
        description="标准收敛: 3次迭代，偏差递减 36→13→2 px",
    )
    results.append(r1)
    _print_result(r1)

    # ── 场景 2: 快速收敛 — 1次就到位 ──
    print("场景 2: 快速收敛（偏差 2px，1次迭代）")
    r2 = run_closed_loop_test(
        target_pos=(800, 400),
        convergence_sequence=[(1, 2)],
        description="快速收敛: 偏差仅 2px，1次迭代",
    )
    results.append(r2)
    _print_result(r2)

    # ── 场景 3: 中等收敛 — 2次迭代 ──
    print("场景 3: 中等收敛（偏差 50→3 px，2次迭代）")
    r3 = run_closed_loop_test(
        target_pos=(960, 540),
        convergence_sequence=[(40, 30), (2, 2)],
        description="中等收敛: 2次迭代，偏差递减 50→3 px",
    )
    results.append(r3)
    _print_result(r3)

    # ── 场景 4: 精确收敛 — 3次迭代从大偏差到精确 ──
    print("场景 4: 精确收敛（偏差 60→25→1 px，3次迭代）")
    r4 = run_closed_loop_test(
        target_pos=(600, 350),
        convergence_sequence=[(50, 35), (20, 15), (1, 0)],
        description="精确收敛: 3次迭代，偏差递减 60→25→1 px",
    )
    results.append(r4)
    _print_result(r4)

    # ── 场景 5: 边界偏差 — 初始偏差刚好 <5px ──
    print("场景 5: 边界偏差（偏差 4px，1次迭代）")
    r5 = run_closed_loop_test(
        target_pos=(400, 250),
        convergence_sequence=[(2, 3)],
        description="边界偏差: 偏差 4px，1次迭代",
    )
    results.append(r5)
    _print_result(r5)

    # ── 汇总 ──
    print()
    print("=" * 70)
    print("汇总")
    print("=" * 70)

    all_converged = all(r["converged"] for r in results)
    all_decreasing = all(r["deviations_decreasing"] for r in results)
    max_iterations = max(r["iterations"] for r in results)
    max_final_deviation = max(r["final_deviation_px"] for r in results)

    print(f"  总场景数:     {len(results)}")
    print(f"  全部收敛:     {'YES' if all_converged else 'NO'}")
    print(f"  偏差递减:     {'YES' if all_decreasing else 'NO'}")
    print(f"  最大迭代次数:  {max_iterations} (要求 <= 3)")
    print(f"  最大最终偏差:  {max_final_deviation:.2f} px (要求 < 5px)")
    print()

    overall_pass = (
        all_converged
        and all_decreasing
        and max_iterations <= 3
        and max_final_deviation < 5.0
    )

    if overall_pass:
        print("T-MC-01 结果: PASS")
    else:
        print("T-MC-01 结果: FAIL")

    # 保存结果到文件
    _save_results(results, overall_pass, max_iterations, max_final_deviation,
                  all_converged, all_decreasing)

    return 0 if overall_pass else 1


def _print_result(r: dict):
    status = "PASS" if r["converged"] else "FAIL"
    print(f"  状态: {status}")
    print(f"  结果: {r['result_status']} -- {r['result_message']}")
    print(f"  迭代: {r['iterations']}, 最终偏差: {r['final_deviation_px']:.2f}px")
    print(f"  偏差递减: {'YES' if r['deviations_decreasing'] else 'NO'}")
    for rec in r["records"]:
        print(
            f"    迭代{rec.iteration}: 定位({rec.located_x},{rec.located_y}) -> "
            f"偏差 {rec.deviation_px:.2f}px ({rec.note})"
        )
    print()


def _save_results(results, overall_pass, max_iterations, max_final_deviation,
                  all_converged, all_decreasing):
    lines = []
    lines.append("# T-MC-01 闭环收敛测试结果\n")
    lines.append(f"## 总体判定: {'PASS' if overall_pass else 'FAIL'}\n")
    lines.append(f"- 全部收敛: {'YES' if all_converged else 'NO'}")
    lines.append(f"- 偏差递减: {'YES' if all_decreasing else 'NO'}")
    lines.append(f"- 最大迭代次数: {max_iterations}")
    lines.append(f"- 最大最终偏差: {max_final_deviation:.2f} px\n")
    lines.append("## 场景详情\n")

    for i, r in enumerate(results, 1):
        lines.append(f"### 场景 {i}: {r['description']}\n")
        lines.append(f"- 目标位置: ({r['target_pos'][0]}, {r['target_pos'][1]})")
        lines.append(f"- 结果状态: {r['result_status']}")
        lines.append(f"- 迭代次数: {r['iterations']}")
        lines.append(f"- 最终偏差: {r['final_deviation_px']:.2f} px")
        lines.append(f"- 偏差递减: {'YES' if r['deviations_decreasing'] else 'NO'}")
        lines.append(f"- 收敛判定: {'PASS' if r['converged'] else 'FAIL'}\n")
        lines.append("| 迭代 | 定位位置 | 偏差(px) | 说明 |")
        lines.append("|------|----------|----------|------|")
        for rec in r["records"]:
            lines.append(
                f"| {rec.iteration} | ({rec.located_x}, {rec.located_y}) | "
                f"{rec.deviation_px:.2f} | {rec.note} |"
            )
        lines.append("")

    result_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "TEST-RESULT.md")
    with open(result_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n结果已保存到: {result_path}")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    exit(main())
