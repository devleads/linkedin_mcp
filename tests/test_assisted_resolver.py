"""Policy tests for bounded assisted page recovery."""

from unittest.mock import AsyncMock

import pytest

from linkedin_mcp.linkedin.assisted import AssistedResolver
from linkedin_mcp.linkedin.observation import ElementCandidate, PageObservation
from linkedin_mcp.linkedin.page_state import PageState


@pytest.mark.asyncio
async def test_write_effect_aborts_without_calling_model():
    model = AsyncMock()
    resolver = AssistedResolver(model)
    decision = await resolver.resolve(PageObservation(url="https://www.linkedin.com/feed/"), PageState.READY_FEED, effect="write")
    assert decision.action == "abort"
    model.assert_not_awaited()


@pytest.mark.asyncio
async def test_challenge_aborts_without_calling_model():
    model = AsyncMock()
    resolver = AssistedResolver(model)
    decision = await resolver.resolve(PageObservation(url="https://www.linkedin.com/checkpoint/"), PageState.CHECKPOINT, effect="read")
    assert decision.action == "abort"
    model.assert_not_awaited()


@pytest.mark.asyncio
async def test_candidate_must_come_from_enumerated_set():
    model = AsyncMock(return_value={"action": "select_candidate", "candidate_ref": "e999", "confidence": 0.9})
    resolver = AssistedResolver(model)
    observation = PageObservation(
        url="https://www.linkedin.com/feed/",
        candidates=(ElementCandidate("e1", role="button", name="Show more"),),
    )
    decision = await resolver.resolve(observation, PageState.READY_FEED, effect="read")
    assert decision.action == "abort"
    assert decision.evidence == ("candidate_out_of_bounds",)
