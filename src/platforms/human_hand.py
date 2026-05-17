"""拟人手部模拟器。

在 PlatformAdapter 之上提供拟人化的鼠标/键盘操作，
让机器操作更接近真人行为，降低被自动化检测的风险。

Step 9 升级：
- 贝塞尔曲线 + 随机控制点偏移
- 非线性速度（缓入缓出）
- 轨迹微抖动（±1-2px）
- 点击按下/抬起分离（mouse_down / mouse_up）
- 按压时长随机化（50-150ms）
- 点击后微小移动（±3px）

Step 10 升级：
- 键盘按键间隔正态分布（30-120ms）
- 偶尔退格+重输（模拟打字纠错，概率 2%）
- 中英文切换增加延迟
- 剪贴板粘贴前等待（200-500ms）
"""

from __future__ import annotations

import asyncio
import math
import random
import string
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.platforms.base import PlatformAdapter


@dataclass
class HumanHandConfig:
    """拟人手部配置。"""

    # ── 鼠标相关 ──
    move_speed: float = 1.0            # 移动速度倍率
    click_offset_range: int = 3        # 点击偏移范围（像素）
    bezier_control_points: int = 3     # 贝塞尔曲线控制点数量
    jitter_range: float = 2.0          # 鼠标轨迹抖动范围（像素）
    press_duration_min: float = 0.05   # 最小按压时长（秒）
    press_duration_max: float = 0.15   # 最大按压时长（秒）
    post_click_move_range: int = 3     # 点击后微移范围（像素）

    # ── 键盘相关（Step 10）──
    typo_probability: float = 0.02     # 打错概率（2%）
    type_interval_min: float = 0.03    # 按键间隔最小值（30ms）
    type_interval_max: float = 0.12    # 按键间隔最大值（120ms）
    type_interval_mu: float = 0.075    # 按键间隔正态分布均值（75ms）
    type_interval_sigma: float = 0.02  # 按键间隔正态分布标准差（20ms）
    lang_switch_delay_min: float = 0.15  # 中英文切换延迟最小（150ms）
    lang_switch_delay_max: float = 0.40  # 中英文切换延迟最大（400ms）
    paste_delay_min: float = 0.20      # 粘贴前延迟最小（200ms）
    paste_delay_max: float = 0.50      # 粘贴前延迟最大（500ms）


class HumanHand:
    """拟人手部模拟器 - 让机器操作看起来像真人。"""

    _PUNCTUATION = set("，。！？、；：""''…—,.\'\"!?;:")

    def __init__(self, adapter: PlatformAdapter, config: HumanHandConfig | None = None):
        self._adapter = adapter
        self._config = config or HumanHandConfig()

    # ================================================================
    # 鼠标操作
    # ================================================================

    async def human_move_to(
        self, x: int, y: int, duration: float | None = None
    ) -> None:
        """拟人移动鼠标 - 贝塞尔曲线路径 + 非线性速度 + 随机抖动。

        路径特征：
        - 贝塞尔曲线：起止点 + 随机偏移的中间控制点
        - 非线性速度：缓入缓出（启动慢 → 中间快 → 接近目标减速）
        - 微抖动：每步加入 ±jitter_range 像素的随机偏移
        """
        # 以 (0, 0) 作为默认起点，真实场景由上层提供
        start_x, start_y = 0, 0
        distance = self._distance(start_x, start_y, x, y)

        if duration is None:
            duration = self._calculate_move_duration(distance) / self._config.move_speed

        # 生成贝塞尔曲线路径（含随机控制点偏移）
        control_points = self._generate_control_points(
            start_x, start_y, x, y,
            num_points=self._config.bezier_control_points,
        )
        num_steps = max(int(duration / 0.010), 10)  # ~10ms per step
        curve = self._bezier_curve(control_points, num_steps)

        # 沿曲线移动，加入抖动 + 非线性速度
        for i, (cx, cy) in enumerate(curve):
            # 微抖动：±jitter_range 像素随机偏移
            jx = cx + random.uniform(-self._config.jitter_range, self._config.jitter_range)
            jy = cy + random.uniform(-self._config.jitter_range, self._config.jitter_range)

            # 非线性速度：缓入缓出控制步进间隔
            t = i / max(num_steps - 1, 1)
            eased = self._ease_in_out(t)
            step_delay = duration / num_steps * (0.5 + eased)

            await self._adapter.move_to(int(jx), int(jy), duration=0)
            await asyncio.sleep(step_delay)

    async def human_click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
    ) -> None:
        """拟人点击 - 移动 + 随机偏移 + mouse_down/mouse_up 分离 + 按压时长 + 点击后微移。

        流程：
        1. 移动到目标附近（加入微小偏移）
        2. 短暂停顿
        3. mouse_down（按下）
        4. 按压保持 50-150ms
        5. mouse_up（抬起）
        6. 微小移动（±post_click_move_range 像素）
        """
        # 移动到目标附近（加入微小偏移）
        offset_x = random.randint(-self._config.click_offset_range, self._config.click_offset_range)
        offset_y = random.randint(-self._config.click_offset_range, self._config.click_offset_range)
        target_x = x + offset_x
        target_y = y + offset_y
        await self.human_move_to(target_x, target_y)

        # 随机短暂停顿 50-200ms
        await asyncio.sleep(random.uniform(0.05, 0.2))

        for _ in range(clicks):
            # 按下（mouse_down）
            await self._mouse_down(target_x, target_y, button)

            # 按压保持 50-150ms（随机化）
            press_duration = random.uniform(
                self._config.press_duration_min,
                self._config.press_duration_max,
            )
            await asyncio.sleep(press_duration)

            # 抬起（mouse_up）
            await self._mouse_up(target_x, target_y, button)

            # 多次点击间隔
            if clicks > 1:
                await asyncio.sleep(random.uniform(0.05, 0.15))

        # 点击后微小移动
        if self._config.post_click_move_range > 0:
            micro_x = target_x + random.randint(
                -self._config.post_click_move_range,
                self._config.post_click_move_range,
            )
            micro_y = target_y + random.randint(
                -self._config.post_click_move_range,
                self._config.post_click_move_range,
            )
            await self._adapter.move_to(micro_x, micro_y, duration=0)

        # 点击后随机停顿
        await asyncio.sleep(random.uniform(0.03, 0.1))

    async def _mouse_down(self, x: int, y: int, button: str = "left") -> None:
        """鼠标按下操作。

        优先使用 adapter.mouse_down，不可用时回退到 pyautogui.mouseDown。
        """
        if hasattr(self._adapter, "mouse_down") and callable(getattr(self._adapter, "mouse_down")):
            await self._adapter.mouse_down(x, y, button=button)
        else:
            # 回退：使用 pyautogui
            import pyautogui
            pyautogui.mouseDown(x=x, y=y, button=button)

    async def _mouse_up(self, x: int, y: int, button: str = "left") -> None:
        """鼠标抬起操作。

        优先使用 adapter.mouse_up，不可用时回退到 pyautogui.mouseUp。
        """
        if hasattr(self._adapter, "mouse_up") and callable(getattr(self._adapter, "mouse_up")):
            await self._adapter.mouse_up(x, y, button=button)
        else:
            # 回退：使用 pyautogui
            import pyautogui
            pyautogui.mouseUp(x=x, y=y, button=button)

    async def human_double_click(self, x: int, y: int) -> None:
        """拟人双击。"""
        await self.human_click(x, y, button="left", clicks=1)
        await asyncio.sleep(random.uniform(0.08, 0.2))
        await self.human_click(x, y, button="left", clicks=1)

    async def human_right_click(self, x: int, y: int) -> None:
        """拟人右键点击。"""
        await self.human_click(x, y, button="right", clicks=1)

    async def human_drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float | None = None,
    ) -> None:
        """拟人拖拽 - 移动到起点 + 按下 + 拟人移动到终点 + 释放。"""
        # 先移动到起点
        await self.human_move_to(start_x, start_y)
        await asyncio.sleep(random.uniform(0.05, 0.15))

        # 按下
        await self._mouse_down(start_x, start_y)
        await asyncio.sleep(random.uniform(0.05, 0.1))

        # 拟人移动到终点
        dist = self._distance(start_x, start_y, end_x, end_y)
        if duration is None:
            duration = self._calculate_move_duration(dist) / self._config.move_speed

        # 生成贝塞尔曲线拖拽路径
        control_points = self._generate_control_points(
            start_x, start_y, end_x, end_y,
            num_points=self._config.bezier_control_points,
        )
        num_steps = max(int(duration / 0.010), 10)
        curve = self._bezier_curve(control_points, num_steps)

        for i, (cx, cy) in enumerate(curve):
            jx = cx + random.uniform(-self._config.jitter_range, self._config.jitter_range)
            jy = cy + random.uniform(-self._config.jitter_range, self._config.jitter_range)
            t = i / max(num_steps - 1, 1)
            eased = self._ease_in_out(t)
            step_delay = duration / num_steps * (0.5 + eased)
            await self._adapter.move_to(int(jx), int(jy), duration=0)
            await asyncio.sleep(step_delay)

        # 释放
        await self._mouse_up(end_x, end_y)
        await asyncio.sleep(random.uniform(0.03, 0.1))

    async def human_scroll(self, clicks: int = 3, direction: str = "down") -> None:
        """拟人滚动 - 分段滚动，每段随机间隔。"""
        segments = random.randint(1, max(clicks, 1))
        per_segment = max(clicks // segments, 1)
        remainder = clicks - per_segment * segments

        for i in range(segments):
            amount = per_segment + (1 if i < remainder else 0)
            await self._adapter.scroll(clicks=amount, direction=direction)
            if i < segments - 1:
                await asyncio.sleep(random.uniform(0.05, 0.15))

    # ================================================================
    # 键盘操作（Step 10 升级）
    # ================================================================

    async def human_type(self, text: str, base_interval: float = 0.05) -> None:
        """拟人打字 - 正态分布间隔 + 偶尔退格纠错 + 中英文切换延迟。

        特征：
        - 按键间隔：正态分布（均值 75ms，σ 20ms），裁剪到 30-120ms
        - 打字纠错：概率 2%，输入错误字符 → 停顿 → 退格 → 重输正确字符
        - 中英文切换：检测到语言切换时增加 150-400ms 延迟
        - 标点/空格后额外停顿
        """
        prev_is_cjk: bool | None = None  # 上一个字符是否为中文（None 表示初始状态）

        for ch in text:
            # 检测中英文切换
            cur_is_cjk = self._is_cjk_char(ch)
            if prev_is_cjk is not None and cur_is_cjk != prev_is_cjk:
                # 语言切换，增加延迟
                switch_delay = random.uniform(
                    self._config.lang_switch_delay_min,
                    self._config.lang_switch_delay_max,
                )
                await asyncio.sleep(switch_delay)
            prev_is_cjk = cur_is_cjk

            # 偶尔打错（仅对非空白字符）
            if (
                random.random() < self._config.typo_probability
                and ch.strip()
            ):
                wrong_char = random.choice(string.ascii_lowercase)
                await self._adapter.type_text(wrong_char, interval=0)
                await asyncio.sleep(random.uniform(0.1, 0.3))  # 意识到打错了

                await self._adapter.press_key("backspace")
                await asyncio.sleep(random.uniform(0.05, 0.15))  # 退格后停顿

            # 正态分布按键间隔，裁剪到 30-120ms
            interval = self._generate_type_interval()
            await self._adapter.type_text(ch, interval=interval)

            if ch in self._PUNCTUATION:
                await asyncio.sleep(random.uniform(0.1, 0.4))

            if ch == " ":
                await asyncio.sleep(random.uniform(0.05, 0.2))

    async def human_paste(self, text: str) -> None:
        """拟人剪贴板粘贴 - 粘贴前等待 200-500ms。

        流程：
        1. 随机等待 200-500ms（模拟"思考"或"准备粘贴"）
        2. 复制文本到剪贴板
        3. 执行 Ctrl+V 粘贴
        """
        # 粘贴前等待
        pre_delay = random.uniform(
            self._config.paste_delay_min,
            self._config.paste_delay_max,
        )
        await asyncio.sleep(pre_delay)

        # 复制到剪贴板
        try:
            import pyperclip
            pyperclip.copy(text)
        except ImportError:
            from src.platforms.windows import _paste_via_clipboard
            _paste_via_clipboard(text)
            return

        # 执行粘贴
        await self._adapter.hotkey("ctrl", "v")

    async def human_press_key(self, key: str) -> None:
        """拟人按键 - 按下后随机保持时间。"""
        await self._adapter.press_key(key)
        await asyncio.sleep(random.uniform(0.05, 0.15))

    async def human_hotkey(self, *keys: str) -> None:
        """拟人组合键 - 按键间有微小间隔。"""
        await asyncio.sleep(random.uniform(0.03, 0.08))
        await self._adapter.hotkey(*keys)
        await asyncio.sleep(random.uniform(0.05, 0.15))

    # ================================================================
    # 辅助方法
    # ================================================================

    def _bezier_curve(
        self,
        points: list[tuple[float, float]],
        num_steps: int,
    ) -> list[tuple[float, float]]:
        """生成贝塞尔曲线上的点。

        使用 de Casteljau 算法，支持任意阶贝塞尔曲线。
        """
        if not points:
            return []
        if len(points) == 1:
            return [points[0]] * num_steps

        result: list[tuple[float, float]] = []
        n = len(points) - 1

        for step in range(num_steps):
            t = step / max(num_steps - 1, 1)
            work = [list(p) for p in points]
            for level in range(1, n + 1):
                for i in range(n - level + 1):
                    work[i][0] = (1 - t) * work[i][0] + t * work[i + 1][0]
                    work[i][1] = (1 - t) * work[i][1] + t * work[i + 1][1]
            result.append((work[0][0], work[0][1]))

        return result

    def _ease_in_out(self, t: float) -> float:
        """缓入缓出函数（三次缓动）。

        t ∈ [0, 1] → [0, 1]
        特征：启动慢 → 中间快 → 接近目标减速
        """
        if t < 0.5:
            return 4 * t * t * t
        else:
            p = -2 * t + 2
            return 1 - p * p * p / 2

    def _random_offset(self, base: float, ratio: float = 0.5) -> float:
        """在 base ± base*ratio 范围内随机。"""
        return base + random.uniform(-base * ratio, base * ratio)

    def _distance(self, x1: int, y1: int, x2: int, y2: int) -> float:
        """计算两点距离。"""
        return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5

    def _calculate_move_duration(self, distance: float) -> float:
        """根据距离计算移动时间。

        - 短距离（<200px）：约 0.3s
        - 中距离（1000px）：约 0.8s
        - 上限：2s
        """
        if distance <= 0:
            return 0.1
        duration = 0.2 + 0.1 * math.log10(max(distance, 1))
        return min(max(duration, 0.15), 2.0)

    def _generate_control_points(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        num_points: int = 3,
    ) -> list[tuple[float, float]]:
        """在起止点之间生成随机贝塞尔曲线控制点。

        控制点沿起止点连线分布，但加入与距离成比例的随机偏移，
        使曲线呈现自然的弧度，而非机械的直线运动。
        """
        points: list[tuple[float, float]] = [(start_x, start_y)]

        for i in range(1, num_points + 1):
            t = i / (num_points + 1)
            # 线性插值基础位置
            bx = start_x + (end_x - start_x) * t
            by = start_y + (end_y - start_y) * t
            # 加入随机偏移（偏移量与距离相关，比例 0.3）
            offset_scale = self._distance(
                int(start_x), int(start_y), int(end_x), int(end_y)
            ) * 0.3
            bx += random.uniform(-offset_scale, offset_scale)
            by += random.uniform(-offset_scale, offset_scale)
            points.append((bx, by))

        points.append((end_x, end_y))
        return points

    def _is_cjk_char(self, ch: str) -> bool:
        """判断字符是否为中日韩文字。"""
        cp = ord(ch)
        # CJK Unified Ideographs: U+4E00–U+9FFF
        # CJK Extension A: U+3400–U+4DBF
        # CJK Extension B: U+20000–U+2A6DF
        # CJK Compatibility Ideographs: U+F900–U+FAFF
        # Full-width forms: U+FF00–U+FFEF
        # CJK Symbols and Punctuation: U+3000–U+303F
        # Hiragana: U+3040–U+309F, Katakana: U+30A0–U+30FF
        return (
            (0x4E00 <= cp <= 0x9FFF)
            or (0x3400 <= cp <= 0x4DBF)
            or (0x20000 <= cp <= 0x2A6DF)
            or (0xF900 <= cp <= 0xFAFF)
            or (0x3000 <= cp <= 0x303F)
            or (0x3040 <= cp <= 0x309F)
            or (0x30A0 <= cp <= 0x30FF)
        )

    def _generate_type_interval(self) -> float:
        """生成正态分布的按键间隔，裁剪到 [min, max] 范围。

        使用高斯分布（均值 75ms，σ 20ms），结果裁剪到 30-120ms。
        """
        raw = random.gauss(self._config.type_interval_mu, self._config.type_interval_sigma)
        return max(self._config.type_interval_min, min(self._config.type_interval_max, raw))
