"""Human-like behavior simulation for browser automation.

Provides randomized delays, mouse movements, typing cadence, and scroll
patterns that mimic real user interaction. These behaviors are critical
for avoiding bot detection on LinkedIn.
"""

import asyncio
import math
import random
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class HumanBehavior:
    """Simulates human-like behavior in browser interactions.

    All methods are static or use the page instance passed to them,
    making this class stateless and safe to share across sessions.
    """

    # ── Basic delays ──────────────────────────────────────────────

    @staticmethod
    async def delay(min_ms: int = 500, max_ms: int = 2000) -> None:
        """Random delay between actions.

        Args:
            min_ms: Minimum delay in milliseconds
            max_ms: Maximum delay in milliseconds
        """
        delay_ms = random.randint(min_ms, max_ms)
        await asyncio.sleep(delay_ms / 1000)

    @staticmethod
    async def typing_delay() -> None:
        """Delay between keystrokes (50-150ms)."""
        await asyncio.sleep(random.randint(50, 150) / 1000)

    @staticmethod
    async def page_load_delay() -> None:
        """Delay after page load (2-5 seconds)."""
        await asyncio.sleep(random.uniform(2.0, 5.0))

    @staticmethod
    async def action_delay() -> None:
        """Delay before an action like click (300-800ms)."""
        await asyncio.sleep(random.uniform(0.3, 0.8))

    @staticmethod
    async def scroll_delay() -> None:
        """Delay between scroll actions (500-1500ms)."""
        await asyncio.sleep(random.uniform(0.5, 1.5))

    # ── Reading simulation ────────────────────────────────────────

    @staticmethod
    async def reading_delay(text_length: int) -> None:
        """Simulate reading time based on text length.

        Args:
            text_length: Number of characters in text
        """
        # Average reading speed: ~250 words per minute
        # Average word length: ~5 characters
        words = text_length / 5
        reading_time = (words / 250) * 60  # seconds
        # Add some variance
        reading_time = reading_time * random.uniform(0.8, 1.2)
        # Cap at 10 seconds
        reading_time = min(reading_time, 10.0)
        # Minimum 1 second
        reading_time = max(reading_time, 1.0)
        await asyncio.sleep(reading_time)

    @staticmethod
    async def human_pause(page, min_ms: int = 500, max_ms: int = 2000) -> None:
        """Pause for a random duration to mimic human think/read time.

        Occasionally (10%) adds a longer "reading" pause on top, since
        real users don't act at perfectly uniform intervals.

        Args:
            page: The Patchright Page instance (for wait_for_timeout).
            min_ms: Minimum pause in milliseconds.
            max_ms: Maximum pause in milliseconds.
        """
        delay_ms = random.randint(min_ms, max_ms)
        # 10% chance of a longer "reading" pause
        if min_ms != max_ms and random.random() < 0.1:
            delay_ms += random.randint(600, 1800)
        await page.wait_for_timeout(delay_ms)

    # ── Scroll helpers ────────────────────────────────────────────

    @staticmethod
    def random_scroll_amount(base: int = 400) -> int:
        """Get random scroll amount with variance.

        Args:
            base: Base scroll amount in pixels

        Returns:
            Scroll amount with ±20% variance
        """
        variance = base * 0.2
        return int(base + random.uniform(-variance, variance))

    # ── Typing helpers ────────────────────────────────────────────

    @staticmethod
    def get_typing_speed() -> int:
        """Get random typing speed (delay between keystrokes in ms)."""
        return random.randint(50, 150)

    @staticmethod
    async def human_type(page, selector: str, text: str) -> bool:
        """Type text into a field with a human-like cadence.

        Focuses the field, clears it, then types character-by-character
        with randomized per-key delays and occasional longer pauses.
        Falls back to `fill()` if `press_sequentially` is unavailable.

        Args:
            page: The Patchright Page instance.
            selector: CSS selector for the input field.
            text: The text to type.

        Returns:
            True if typing succeeded, False on error.
        """
        try:
            locator = page.locator(selector).first
            # Click with a small delay to simulate focus
            await locator.click(delay=random.randint(40, 140))
            # Clear the field first
            await locator.fill("")
            # Type character-by-character with randomized delays
            try:
                for char in text:
                    await locator.press_sequentially(
                        char, delay=random.randint(55, 185)
                    )
                    # 6% chance of a longer pause (thinking/reading)
                    if random.random() < 0.06:
                        await page.wait_for_timeout(random.randint(200, 600))
            except Exception:
                # Fallback: some elements don't support press_sequentially
                await locator.fill(text)
            return True
        except Exception as e:
            logger.warning(f"[human_type] Failed for {selector}: {e}")
            return False

    # ── Mouse movement helpers ────────────────────────────────────

    @staticmethod
    async def mouse_movement_delay() -> None:
        """Delay for mouse movement simulation (100-300ms)."""
        await asyncio.sleep(random.uniform(0.1, 0.3))

    @staticmethod
    async def human_mouse_and_scroll(page) -> None:
        """Move the mouse and scroll randomly to simulate idle user activity.

        Moves the mouse along a few intermediate points and optionally
        scrolls a little, mimicking the small, non-instant movements a
        human makes while reading a page. Best-effort — never throws.

        Args:
            page: The Patchright Page instance.
        """
        try:
            viewport = page.viewport_size or {"width": 1280, "height": 720}
            width = viewport.get("width", 1280)
            height = viewport.get("height", 720)

            # 2-4 random mouse movements
            steps = random.randint(2, 4)
            for _ in range(steps):
                await page.mouse.move(
                    random.randint(40, width - 40),
                    random.randint(40, height - 40),
                    steps=random.randint(3, 8),
                )
                await page.wait_for_timeout(random.randint(40, 160))

            # 70% chance of scrolling
            if random.random() < 0.7:
                await page.mouse.wheel(0, random.randint(120, 520))
                await page.wait_for_timeout(random.randint(150, 500))
        except Exception:
            # Non-fatal — mouse/scroll emulation is best-effort.
            pass

    @staticmethod
    def random_viewport_offset() -> Tuple[int, int]:
        """Get random offset for click position (simulates imprecise clicking).

        Returns:
            Tuple of (x_offset, y_offset) in pixels
        """
        return (
            random.randint(-3, 3),
            random.randint(-3, 3),
        )

    @staticmethod
    def random_mouse_steps(distance: float) -> int:
        """Return mouse movement steps based on travel distance."""
        if distance <= 0:
            return 1
        return max(6, min(40, int(distance / 18) + random.randint(3, 8)))

    @staticmethod
    def build_mouse_path(
        start: Tuple[float, float], end: Tuple[float, float], steps: int
    ) -> list[Tuple[float, float]]:
        """Build a slightly curved cursor path from start to end.

        Uses quadratic Bezier interpolation with a randomized midpoint
        to create natural-looking mouse trajectories.

        Args:
            start: Starting (x, y) coordinates.
            end: Ending (x, y) coordinates.
            steps: Number of interpolation steps.

        Returns:
            List of (x, y) points along the path.
        """
        sx, sy = start
        ex, ey = end
        if steps <= 1:
            return [(ex, ey)]

        # Randomized midpoint for Bezier curve
        mx = (sx + ex) / 2 + random.uniform(-40, 40)
        my = (sy + ey) / 2 + random.uniform(-40, 40)

        points: list[Tuple[float, float]] = []
        for i in range(1, steps + 1):
            t = i / steps
            # Quadratic Bezier interpolation
            x = ((1 - t) ** 2 * sx) + (2 * (1 - t) * t * mx) + ((t**2) * ex)
            y = ((1 - t) ** 2 * sy) + (2 * (1 - t) * t * my) + ((t**2) * ey)
            points.append((x, y))
        return points

    # ── Click timing helpers ──────────────────────────────────────

    @staticmethod
    async def hover_delay() -> None:
        """Delay while hovering on target before click."""
        await asyncio.sleep(random.uniform(0.1, 0.35))

    @staticmethod
    async def post_click_delay() -> None:
        """Delay immediately after click."""
        await asyncio.sleep(random.uniform(0.18, 0.45))

    @staticmethod
    def click_hold_ms() -> int:
        """Mouse button hold duration in milliseconds."""
        return random.randint(35, 120)

    @staticmethod
    def distance(
        start: Tuple[float, float], end: Tuple[float, float]
    ) -> float:
        """Euclidean distance between two points."""
        return math.hypot(end[0] - start[0], end[1] - start[1])
