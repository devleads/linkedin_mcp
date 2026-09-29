"""Stateful browser interaction primitives shared by page adapters."""

from dataclasses import dataclass
from enum import StrEnum
import math
import random
from typing import Any, Optional


class ActivityPhase(StrEnum):
    IDLE = "idle"
    READING = "reading"
    SEARCHING = "searching"
    COMPOSING = "composing"
    REVIEWING = "reviewing"


@dataclass(frozen=True)
class BehaviorProfile:
    """Stable interaction ranges for one browser profile."""

    typing_delay_min_ms: int = 55
    typing_delay_max_ms: int = 185
    pointer_pixels_per_second: float = 900.0
    minimum_pointer_seconds: float = 0.12
    maximum_pointer_seconds: float = 1.25


@dataclass
class InteractionState:
    cursor_x: Optional[float] = None
    cursor_y: Optional[float] = None
    phase: ActivityPhase = ActivityPhase.IDLE
    page_revision: int = 0


class InteractionController:
    """Maintain cursor, focus, and task phase across sequential actions."""

    def __init__(self, profile: BehaviorProfile | None = None, seed: int | None = None):
        self.profile = profile or BehaviorProfile()
        self.state = InteractionState()
        self._random = random.Random(seed)

    def set_phase(self, phase: ActivityPhase) -> None:
        self.state.phase = phase

    def navigation_completed(self) -> None:
        self.state.page_revision += 1
        self.state.phase = ActivityPhase.READING

    async def click(self, page: Any, locator: Any, timeout: int = 5000) -> bool:
        await locator.wait_for(state="visible", timeout=timeout)
        await locator.scroll_into_view_if_needed(timeout=timeout)
        box = await locator.bounding_box()
        if not box or box["width"] <= 0 or box["height"] <= 0:
            return False

        target_x = box["x"] + box["width"] * self._random.uniform(0.35, 0.65)
        target_y = box["y"] + box["height"] * self._random.uniform(0.35, 0.65)
        await self._move_pointer(page, target_x, target_y)
        await page.mouse.down()
        await page.wait_for_timeout(self._random.randint(35, 120))
        await page.mouse.up()
        return True

    async def type_text(self, page: Any, locator: Any, text: str) -> bool:
        await locator.wait_for(state="visible")
        await locator.scroll_into_view_if_needed()
        await locator.click()
        await locator.fill("")
        self.state.phase = ActivityPhase.COMPOSING
        for character in text:
            delay = self._random.randint(
                self.profile.typing_delay_min_ms,
                self.profile.typing_delay_max_ms,
            )
            await locator.press_sequentially(character, delay=delay)
        self.state.phase = ActivityPhase.REVIEWING
        return True

    async def scroll_toward(self, page: Any, pixels: int) -> None:
        self.state.phase = ActivityPhase.READING
        await page.mouse.wheel(0, pixels)

    async def _move_pointer(self, page: Any, target_x: float, target_y: float) -> None:
        viewport = page.viewport_size or {"width": 1280, "height": 720}
        start_x = self.state.cursor_x
        start_y = self.state.cursor_y
        if start_x is None or start_y is None:
            start_x = viewport["width"] / 2
            start_y = viewport["height"] / 2

        distance = math.hypot(target_x - start_x, target_y - start_y)
        duration = min(
            self.profile.maximum_pointer_seconds,
            max(
                self.profile.minimum_pointer_seconds,
                distance / self.profile.pointer_pixels_per_second,
            ),
        )
        steps = max(2, min(40, round(duration / 0.016)))
        await page.mouse.move(target_x, target_y, steps=steps)
        self.state.cursor_x = target_x
        self.state.cursor_y = target_y
