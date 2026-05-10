"""MotorController 闭环控制器。

整合 VisionEye（感知）+ HumanHand（执行），实现完整的
'看 → 判断 → 动作 → 验证' 闭环控制循环。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable, Awaitable

from loguru import logger

if TYPE_CHECKING:
    from src.perception.vision_eye import VisionEye
    from src.platforms.human_hand import HumanHand
    from src.platforms.base import PlatformAdapter


class ActionStatus(Enum):
    """动作执行结果状态。"""

    SUCCESS = "success"
    TARGET_NOT_FOUND = "target_not_found"
    ACTION_FAILED = "action_failed"
    VERIFICATION_FAILED = "verification_failed"
    TIMEOUT = "timeout"


@dataclass
class ActionResult:
    """动作执行结果。"""

    status: ActionStatus
    message: str = ""
    attempts: int = 0
    duration_ms: float = 0.0
    target_coords: tuple[int, int] | None = None


@dataclass
class MotorControllerConfig:
    """闭环控制器配置。"""

    max_attempts: int = 3  # 最大重试次数
    verify_delay: float = 0.5  # 动作后等待验证的延迟（秒）
    action_timeout: float = 10.0  # 单次动作超时（秒）
    screenshot_interval: float = 0.3  # 截图间隔（秒）
    click_tolerance: int = 10  # 点击容差（像素）


class MotorController:
    """闭环控制器 - 感知 + 执行 + 验证一体化。

    Usage::

        controller = MotorController(eye, hand, adapter, config)
        result = await controller.click_target("保存按钮")
        result = await controller.type_in_field("用户名输入框", "hello")
        result = await controller.wait_and_click("确认", timeout=5.0)
    """

    def __init__(
        self,
        eye: VisionEye,
        hand: HumanHand,
        adapter: PlatformAdapter,
        config: MotorControllerConfig | None = None,
    ) -> None:
        self._eye = eye
        self._hand = hand
        self._adapter = adapter
        self._config = config or MotorControllerConfig()

    # ── 核心闭环动作 ──────────────────────────────

    async def click_target(
        self,
        target_desc: str,
        target_type: str | None = None,
        verify_change: bool = True,
    ) -> ActionResult:
        """闭环点击目标：查找 → 点击 → 验证。

        1. 截图 + 分析 → find_target
        2. human_click 点击目标坐标
        3. 截图 + 验证目标是否消失/变化
        """
        start = time.monotonic()

        for attempt in range(1, self._config.max_attempts + 1):
            # 1. 截图并分析
            await self._take_screenshot_and_analyze()

            # 2. 查找目标
            match = await self._eye.find_target(target_desc, target_type=target_type)
            if match is None:
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.debug(f"click_target: 目标未找到 (attempt {attempt})")
                if attempt >= self._config.max_attempts:
                    return ActionResult(
                        status=ActionStatus.TARGET_NOT_FOUND,
                        message=f"未找到目标: {target_desc}",
                        attempts=attempt,
                        duration_ms=elapsed_ms,
                    )
                continue

            coords = match.target.center
            logger.debug(f"click_target: 找到目标 {target_desc} at {coords}")

            # 3. 执行点击
            try:
                await self._hand.human_click(coords[0], coords[1])
            except Exception as exc:
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.warning(f"click_target: 点击失败 - {exc}")
                if attempt >= self._config.max_attempts:
                    return ActionResult(
                        status=ActionStatus.ACTION_FAILED,
                        message=f"点击失败: {exc}",
                        attempts=attempt,
                        duration_ms=elapsed_ms,
                        target_coords=coords,
                    )
                continue

            # 4. 验证（可选）
            if verify_change:
                await asyncio.sleep(self._config.verify_delay)
                await self._take_screenshot_and_analyze()
                still_exists = await self._eye.find_target(target_desc, target_type=target_type)
                if still_exists is not None:
                    logger.debug(f"click_target: 验证失败，目标仍在 (attempt {attempt})")
                    if attempt >= self._config.max_attempts:
                        elapsed_ms = (time.monotonic() - start) * 1000
                        return ActionResult(
                            status=ActionStatus.VERIFICATION_FAILED,
                            message=f"点击后目标仍存在: {target_desc}",
                            attempts=attempt,
                            duration_ms=elapsed_ms,
                            target_coords=coords,
                        )
                    continue

            elapsed_ms = (time.monotonic() - start) * 1000
            return ActionResult(
                status=ActionStatus.SUCCESS,
                message=f"成功点击: {target_desc}",
                attempts=attempt,
                duration_ms=elapsed_ms,
                target_coords=coords,
            )

        elapsed_ms = (time.monotonic() - start) * 1000
        return ActionResult(
            status=ActionStatus.TIMEOUT,
            message=f"超过最大重试次数: {target_desc}",
            attempts=self._config.max_attempts,
            duration_ms=elapsed_ms,
        )

    async def type_in_field(
        self,
        field_desc: str,
        text: str,
        press_enter: bool = False,
    ) -> ActionResult:
        """闭环输入文本：查找输入框 → 点击聚焦 → 输入 → 验证。"""
        start = time.monotonic()

        for attempt in range(1, self._config.max_attempts + 1):
            # 1. 截图并分析
            await self._take_screenshot_and_analyze()

            # 2. 查找输入框
            match = await self._eye.find_target(field_desc)
            if match is None:
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.debug(f"type_in_field: 输入框未找到 (attempt {attempt})")
                if attempt >= self._config.max_attempts:
                    return ActionResult(
                        status=ActionStatus.TARGET_NOT_FOUND,
                        message=f"未找到输入框: {field_desc}",
                        attempts=attempt,
                        duration_ms=elapsed_ms,
                    )
                continue

            coords = match.target.center

            # 3. 点击聚焦
            try:
                await self._hand.human_click(coords[0], coords[1])
                await asyncio.sleep(self._config.verify_delay)
            except Exception as exc:
                elapsed_ms = (time.monotonic() - start) * 1000
                if attempt >= self._config.max_attempts:
                    return ActionResult(
                        status=ActionStatus.ACTION_FAILED,
                        message=f"点击输入框失败: {exc}",
                        attempts=attempt,
                        duration_ms=elapsed_ms,
                        target_coords=coords,
                    )
                continue

            # 4. 输入文本
            try:
                await self._hand.human_type(text)
            except Exception as exc:
                elapsed_ms = (time.monotonic() - start) * 1000
                if attempt >= self._config.max_attempts:
                    return ActionResult(
                        status=ActionStatus.ACTION_FAILED,
                        message=f"输入文本失败: {exc}",
                        attempts=attempt,
                        duration_ms=elapsed_ms,
                        target_coords=coords,
                    )
                continue

            # 5. 可选按回车
            if press_enter:
                await self._hand.human_press_key("enter")

            elapsed_ms = (time.monotonic() - start) * 1000
            return ActionResult(
                status=ActionStatus.SUCCESS,
                message=f"成功输入文本到: {field_desc}",
                attempts=attempt,
                duration_ms=elapsed_ms,
                target_coords=coords,
            )

        elapsed_ms = (time.monotonic() - start) * 1000
        return ActionResult(
            status=ActionStatus.TIMEOUT,
            message=f"超过最大重试次数: {field_desc}",
            attempts=self._config.max_attempts,
            duration_ms=elapsed_ms,
        )

    async def wait_and_click(
        self,
        target_desc: str,
        timeout: float = 10.0,
        poll_interval: float = 0.5,
    ) -> ActionResult:
        """等待目标出现后点击（轮询模式）。"""
        start = time.monotonic()

        while (time.monotonic() - start) < timeout:
            await self._take_screenshot_and_analyze()
            match = await self._eye.find_target(target_desc)

            if match is not None:
                coords = match.target.center
                try:
                    await self._hand.human_click(coords[0], coords[1])
                    elapsed_ms = (time.monotonic() - start) * 1000
                    return ActionResult(
                        status=ActionStatus.SUCCESS,
                        message=f"等待并点击: {target_desc}",
                        attempts=1,
                        duration_ms=elapsed_ms,
                        target_coords=coords,
                    )
                except Exception as exc:
                    elapsed_ms = (time.monotonic() - start) * 1000
                    return ActionResult(
                        status=ActionStatus.ACTION_FAILED,
                        message=f"点击失败: {exc}",
                        attempts=1,
                        duration_ms=elapsed_ms,
                        target_coords=coords,
                    )

            await asyncio.sleep(poll_interval)

        elapsed_ms = (time.monotonic() - start) * 1000
        return ActionResult(
            status=ActionStatus.TIMEOUT,
            message=f"等待超时: {target_desc}",
            attempts=0,
            duration_ms=elapsed_ms,
        )

    async def wait_for_target(
        self,
        target_desc: str,
        timeout: float = 10.0,
        poll_interval: float = 0.5,
    ) -> ActionResult:
        """等待目标出现（只等待不点击），返回目标坐标。"""
        start = time.monotonic()

        while (time.monotonic() - start) < timeout:
            await self._take_screenshot_and_analyze()
            match = await self._eye.find_target(target_desc)

            if match is not None:
                coords = match.target.center
                elapsed_ms = (time.monotonic() - start) * 1000
                return ActionResult(
                    status=ActionStatus.SUCCESS,
                    message=f"目标出现: {target_desc}",
                    attempts=1,
                    duration_ms=elapsed_ms,
                    target_coords=coords,
                )

            await asyncio.sleep(poll_interval)

        elapsed_ms = (time.monotonic() - start) * 1000
        return ActionResult(
            status=ActionStatus.TIMEOUT,
            message=f"等待超时: {target_desc}",
            attempts=0,
            duration_ms=elapsed_ms,
        )

    async def scroll_and_find(
        self,
        target_desc: str,
        direction: str = "down",
        max_scrolls: int = 5,
        scroll_clicks: int = 3,
    ) -> ActionResult:
        """滚动查找目标：交替滚动 + 截图查找。"""
        start = time.monotonic()

        for scroll_idx in range(max_scrolls + 1):
            # 先截图查找（第 0 次不滚动）
            await self._take_screenshot_and_analyze()
            match = await self._eye.find_target(target_desc)

            if match is not None:
                coords = match.target.center
                elapsed_ms = (time.monotonic() - start) * 1000
                return ActionResult(
                    status=ActionStatus.SUCCESS,
                    message=f"滚动后找到: {target_desc}",
                    attempts=scroll_idx + 1,
                    duration_ms=elapsed_ms,
                    target_coords=coords,
                )

            # 还没找到且还有滚动次数，滚动一次
            if scroll_idx < max_scrolls:
                await self._hand.human_scroll(clicks=scroll_clicks, direction=direction)
                await asyncio.sleep(self._config.screenshot_interval)

        elapsed_ms = (time.monotonic() - start) * 1000
        return ActionResult(
            status=ActionStatus.TARGET_NOT_FOUND,
            message=f"滚动 {max_scrolls} 次后仍未找到: {target_desc}",
            attempts=max_scrolls + 1,
            duration_ms=elapsed_ms,
        )

    # ── 验证辅助 ──────────────────────────────

    async def _verify_target_gone(
        self,
        target_desc: str,
    ) -> bool:
        """验证目标是否已消失（用于点击后验证）。"""
        await self._take_screenshot_and_analyze()
        match = await self._eye.find_target(target_desc)
        return match is None

    async def _take_screenshot_and_analyze(self) -> None:
        """截图并分析（更新缓存）。"""
        screenshot = await self._adapter.screenshot()
        await self._eye.capture_and_analyze(screenshot)

    # ── 重试逻辑 ──────────────────────────────

    async def _retry_action(
        self,
        action_coro_factory: Callable[[], Awaitable[ActionResult]],
        max_attempts: int | None = None,
    ) -> ActionResult:
        """通用重试包装器。"""
        attempts = max_attempts or self._config.max_attempts
        start = time.monotonic()

        last_result: ActionResult | None = None

        for attempt in range(1, attempts + 1):
            result = await action_coro_factory()
            last_result = result

            if result.status == ActionStatus.SUCCESS:
                result.attempts = attempt
                result.duration_ms = (time.monotonic() - start) * 1000
                return result

        # 所有尝试均失败
        if last_result is not None:
            last_result.attempts = attempts
            last_result.duration_ms = (time.monotonic() - start) * 1000
            return last_result

        elapsed_ms = (time.monotonic() - start) * 1000
        return ActionResult(
            status=ActionStatus.TIMEOUT,
            message="重试耗尽",
            attempts=attempts,
            duration_ms=elapsed_ms,
        )
