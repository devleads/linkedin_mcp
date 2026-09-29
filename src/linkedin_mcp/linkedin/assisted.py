"""Bounded, read-only assisted candidate selection for layout recovery."""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from linkedin_mcp.linkedin.observation import PageObservation
from linkedin_mcp.linkedin.page_state import PageState


STOP_STATES = {
    PageState.LOGIN,
    PageState.AUTH_WALL,
    PageState.CHECKPOINT,
    PageState.CAPTCHA,
    PageState.RATE_LIMIT,
}


@dataclass(frozen=True)
class AssistedDecision:
    action: Literal["select_candidate", "extract_fields", "abort"]
    candidate_ref: str | None
    confidence: float
    evidence: tuple[str, ...]


class AssistedResolver:
    """Validate model output against an observation-local candidate set."""

    def __init__(self, model: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]):
        self._model = model

    async def resolve(
        self,
        observation: PageObservation,
        page_state: PageState,
        *,
        effect: Literal["read", "write"],
    ) -> AssistedDecision:
        if effect != "read" or page_state in STOP_STATES:
            return AssistedDecision("abort", None, 1.0, ("policy_stop",))

        raw = await self._model(observation.safe_model_payload())
        action = raw.get("action")
        if action not in {"select_candidate", "extract_fields", "abort"}:
            return AssistedDecision("abort", None, 1.0, ("invalid_action",))
        reference = raw.get("candidate_ref")
        allowed = {candidate.reference for candidate in observation.candidates}
        if action == "select_candidate" and reference not in allowed:
            return AssistedDecision("abort", None, 1.0, ("candidate_out_of_bounds",))
        try:
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        evidence = tuple(str(value)[:300] for value in raw.get("evidence", [])[:10])
        return AssistedDecision(action, reference, confidence, evidence)
