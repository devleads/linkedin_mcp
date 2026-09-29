"""Base page adapter with centralized observation and state checks."""

from typing import Any, Iterable

from linkedin_mcp.linkedin.observation import ElementCandidate, PageObservation
from linkedin_mcp.linkedin.page_state import PageState, classify_page_state


class UnexpectedPageStateError(RuntimeError):
    def __init__(self, state: PageState, url: str):
        super().__init__(f"Unexpected LinkedIn page state: {state.value}")
        self.state = state
        self.url = url


async def observe_page(page: Any, page_revision: int = 0) -> PageObservation:
    """Collect bounded visible structure without cookies, storage, or hidden text."""
    raw = await page.evaluate(
        """
        () => {
          const visible = (element) => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const nodes = Array.from(document.querySelectorAll('button, a, input, textarea, [role]'))
            .filter(visible)
            .slice(0, 100);
          return {
            readyState: document.readyState,
            visibleText: (document.body && document.body.innerText || '').slice(0, 20000),
            headings: Array.from(document.querySelectorAll('h1,h2,h3')).filter(visible).slice(0, 20).map(el => (el.innerText || '').trim()),
            landmarks: Array.from(document.querySelectorAll('[role="main"],[role="navigation"],[role="dialog"],main,nav')).filter(visible).slice(0, 20).map(el => el.getAttribute('role') || el.tagName.toLowerCase()),
            candidates: nodes.map((el, index) => ({
              reference: `e${index}`,
              role: el.getAttribute('role') || ({BUTTON:'button',A:'link',INPUT:'textbox',TEXTAREA:'textbox'}[el.tagName] || null),
              name: (el.getAttribute('aria-label') || el.innerText || el.getAttribute('placeholder') || '').trim().slice(0, 300),
              disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true')
            }))
          };
        }
        """
    )
    return PageObservation(
        url=page.url,
        title=await page.title(),
        ready_state=raw.get("readyState", ""),
        visible_text=raw.get("visibleText", ""),
        headings=tuple(raw.get("headings", [])),
        landmarks=tuple(raw.get("landmarks", [])),
        candidates=tuple(
            ElementCandidate(
                reference=item["reference"],
                role=item.get("role"),
                name=item.get("name"),
                disabled=item.get("disabled", False),
            )
            for item in raw.get("candidates", [])
        ),
        page_revision=page_revision,
    )


class LinkedInPageAdapter:
    def __init__(self, page: Any, page_revision: int = 0):
        self.page = page
        self.page_revision = page_revision

    async def observe(self) -> PageObservation:
        return await observe_page(self.page, self.page_revision)

    async def require_state(self, allowed: Iterable[PageState]) -> PageObservation:
        observation = await self.observe()
        state = classify_page_state(observation)
        if state not in set(allowed):
            raise UnexpectedPageStateError(state, observation.url)
        return observation

    async def unique_role(self, role: str, name: str):
        locator = self.page.get_by_role(role, name=name, exact=True)
        count = await locator.count()
        if count != 1:
            code = "AMBIGUOUS_TARGET" if count > 1 else "SELECTOR_DRIFT"
            raise RuntimeError(f"{code}: expected one {role} named {name!r}, found {count}")
        candidate = locator.first
        if not await candidate.is_visible() or not await candidate.is_enabled():
            raise RuntimeError("PAGE_NOT_READY: resolved control is not actionable")
        return candidate
