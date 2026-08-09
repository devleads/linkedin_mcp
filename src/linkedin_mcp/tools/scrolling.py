"""Shared scrolling helpers for LinkedIn tools."""

from linkedin_mcp.browser.human import HumanBehavior


async def jittered_safe_scroll_once(
    browser,
    human: HumanBehavior,
    *,
    base_pixels: int = 500,
    delay_min_ms: int = 500,
    delay_max_ms: int = 1200,
    on_navigation_delay_min_ms: int = 1000,
    on_navigation_delay_max_ms: int = 1500,
) -> bool:
    """Perform one randomized safe scroll step and wait for content to settle."""
    pixels = max(200, human.random_scroll_amount(base_pixels))
    ok = await browser.safe_scroll(0, pixels)
    if not ok:
        await human.delay(on_navigation_delay_min_ms, on_navigation_delay_max_ms)
        return False

    await human.delay(delay_min_ms, delay_max_ms)
    return True


async def jittered_safe_scroll_sequence(
    browser,
    human: HumanBehavior,
    *,
    steps: int,
    base_pixels: int,
    delay_min_ms: int,
    delay_max_ms: int,
    on_navigation_delay_min_ms: int = 1000,
    on_navigation_delay_max_ms: int = 1500,
) -> bool:
    """Perform multiple randomized safe scroll steps; stop if navigation interrupts."""
    for _ in range(max(0, steps)):
        ok = await jittered_safe_scroll_once(
            browser,
            human,
            base_pixels=base_pixels,
            delay_min_ms=delay_min_ms,
            delay_max_ms=delay_max_ms,
            on_navigation_delay_min_ms=on_navigation_delay_min_ms,
            on_navigation_delay_max_ms=on_navigation_delay_max_ms,
        )
        if not ok:
            return False
    return True


async def center_first_visible(
    browser,
    human: HumanBehavior,
    *,
    selectors: list[str],
    block: str = "center",
    settle_min_ms: int = 600,
    settle_max_ms: int = 1200,
) -> bool:
    """Center the first visible matching element in viewport."""
    selector_literals = [s for s in selectors if isinstance(s, str) and s.strip()]
    if not selector_literals:
        return False

    centered = await browser.evaluate(
        """
        () => {
            const selectors = __SELECTORS__;
            const block = __BLOCK__;
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };

            for (const sel of selectors) {
                const nodes = Array.from(document.querySelectorAll(sel));
                const target = nodes.find((n) => isVisible(n));
                if (!target) continue;
                target.scrollIntoView({ behavior: 'auto', block });
                return true;
            }
            return false;
        }
        """.replace("__SELECTORS__", repr(selector_literals)).replace("__BLOCK__", repr(block))
    )

    if centered:
        await human.delay(settle_min_ms, settle_max_ms)
    return bool(centered)


async def humanize_post_interaction_viewport(
    browser,
    human: HumanBehavior,
    *,
    selectors: list[str],
    scan_steps: int = 2,
    scan_base_pixels: int = 600,
) -> None:
    """Apply a reusable pre-interaction viewport strategy for post actions."""
    await jittered_safe_scroll_sequence(
        browser,
        human,
        steps=max(1, scan_steps),
        base_pixels=scan_base_pixels,
        delay_min_ms=700,
        delay_max_ms=1300,
        on_navigation_delay_min_ms=1200,
        on_navigation_delay_max_ms=2000,
    )

    centered = await center_first_visible(
        browser,
        human,
        selectors=selectors,
        block="center",
        settle_min_ms=700,
        settle_max_ms=1200,
    )

    if not centered:
        await jittered_safe_scroll_once(
            browser,
            human,
            base_pixels=max(350, scan_base_pixels // 2),
            delay_min_ms=600,
            delay_max_ms=1100,
            on_navigation_delay_min_ms=1000,
            on_navigation_delay_max_ms=1700,
        )
        await center_first_visible(
            browser,
            human,
            selectors=selectors,
            block="center",
            settle_min_ms=600,
            settle_max_ms=1000,
        )
