"""Configurable activity budget tests."""

from linkedin_mcp.activity_policy import ActivityPolicy
from linkedin_mcp.config import Settings


def test_zero_limit_disables_budget(tmp_path):
    settings = Settings(
        _env_file=None,
        browser_profile_root=tmp_path,
        max_profile_write_actions_per_hour=0,
    )
    policy = ActivityPolicy(settings)
    assert all(policy.allow("profile", "write") for _ in range(100))


def test_write_budget_is_per_profile(tmp_path):
    settings = Settings(
        _env_file=None,
        browser_profile_root=tmp_path,
        max_profile_write_actions_per_hour=1,
    )
    policy = ActivityPolicy(settings)
    assert policy.allow("one", "write") is True
    assert policy.allow("one", "write") is False
    assert policy.allow("two", "write") is True
