"""Deterministic page-state and semantic locator tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from linkedin_mcp.linkedin.locators import (
    AmbiguousTargetError,
    SelectorDriftError,
    resolve_semantic_candidate,
)
from linkedin_mcp.linkedin.observation import ElementCandidate, PageObservation
from linkedin_mcp.linkedin.page_state import PageState, classify_page_state
from linkedin_mcp.linkedin.pages.base import LinkedInPageAdapter, observe_page


@pytest.mark.parametrize(
    "url,text,expected",
    [
        ("https://www.linkedin.com/feed/", "", PageState.READY_FEED),
        ("https://www.linkedin.com/in/example/", "", PageState.READY_PROFILE),
        ("https://www.linkedin.com/company/example/", "", PageState.READY_COMPANY),
        ("https://www.linkedin.com/messaging/", "", PageState.READY_MESSAGING),
        ("https://www.linkedin.com/checkpoint/challenge/", "", PageState.CHECKPOINT),
        ("https://www.linkedin.com/feed/", "Complete this CAPTCHA", PageState.CAPTCHA),
        ("https://www.linkedin.com/authwall", "", PageState.AUTH_WALL),
    ],
)
def test_classifies_page(url, text, expected):
    assert classify_page_state(PageObservation(url=url, visible_text=text)) == expected


def test_challenge_takes_precedence_over_application_route():
    observation = PageObservation(
        url="https://www.linkedin.com/feed/",
        visible_text="Security verification required",
    )
    assert classify_page_state(observation) == PageState.CHECKPOINT


def test_semantic_resolution_requires_exactly_one_candidate():
    observation = PageObservation(
        url="https://www.linkedin.com/messaging/",
        candidates=(ElementCandidate("e1", role="button", name="Send"),),
    )
    resolution = resolve_semantic_candidate(observation, role="button", accessible_name="Send")
    assert resolution.candidate.reference == "e1"


def test_semantic_resolution_aborts_on_ambiguity():
    observation = PageObservation(
        url="https://www.linkedin.com/messaging/",
        candidates=(
            ElementCandidate("e1", role="button", name="Send"),
            ElementCandidate("e2", role="button", name="Send"),
        ),
    )
    with pytest.raises(AmbiguousTargetError):
        resolve_semantic_candidate(observation, role="button", accessible_name="Send")


def test_semantic_resolution_ignores_hidden_and_disabled_candidates():
    observation = PageObservation(
        url="https://www.linkedin.com/messaging/",
        candidates=(
            ElementCandidate("e1", role="button", name="Send", visible=False),
            ElementCandidate("e2", role="button", name="Send", disabled=True),
        ),
    )
    with pytest.raises(SelectorDriftError):
        resolve_semantic_candidate(observation, role="button", accessible_name="Send")


@pytest.mark.asyncio
async def test_observer_collects_bounded_structure():
    page = MagicMock(url="https://www.linkedin.com/feed/")
    page.title = AsyncMock(return_value="Feed")
    page.evaluate = AsyncMock(return_value={
        "readyState": "complete",
        "visibleText": "Home feed",
        "headings": ["Home"],
        "landmarks": ["main"],
        "candidates": [{"reference": "e0", "role": "button", "name": "Start a post", "disabled": False}],
    })
    observation = await observe_page(page, page_revision=2)
    assert observation.page_revision == 2
    assert observation.candidates[0].reference == "e0"


@pytest.mark.asyncio
async def test_page_adapter_requires_unique_actionable_role():
    page = MagicMock()
    locator = MagicMock()
    locator.count = AsyncMock(return_value=1)
    candidate = MagicMock()
    candidate.is_visible = AsyncMock(return_value=True)
    candidate.is_enabled = AsyncMock(return_value=True)
    locator.first = candidate
    page.get_by_role.return_value = locator
    resolved = await LinkedInPageAdapter(page).unique_role("button", "Send")
    assert resolved is candidate
