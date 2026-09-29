"""Tests for provider-neutral, fail-closed network route resolution."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from linkedin_mcp.config import Settings
from linkedin_mcp.network import NetworkRouteError, NetworkRouteResolver


def _profile():
    return SimpleNamespace(country="US", state="california", city=None)


def test_direct_route_does_not_initialize_provider(tmp_path):
    settings = Settings(_env_file=None, proxy_provider="none", browser_profile_root=tmp_path)
    with patch("linkedin_mcp.network.resolver.get_proxy_dict_for_profile") as provider:
        route = NetworkRouteResolver(settings).resolve(_profile())
    assert route.kind == "direct"
    assert route.provider == "none"
    assert route.as_browser_proxy() is None
    provider.assert_not_called()


def test_named_provider_failure_never_falls_back(tmp_path):
    settings = Settings(
        _env_file=None,
        proxy_provider="oxylabs",
        proxy_required=False,
        browser_profile_root=tmp_path,
    )
    with patch(
        "linkedin_mcp.network.resolver.get_proxy_dict_for_profile",
        side_effect=RuntimeError("secret provider detail"),
    ):
        with pytest.raises(NetworkRouteError, match="configured oxylabs route"):
            NetworkRouteResolver(settings).resolve(_profile())


def test_proxy_repr_redacts_credentials(tmp_path):
    settings = Settings(
        _env_file=None,
        proxy_provider="ipfoxy",
        linkedin_credential_encryption_key="route-key",
        browser_profile_root=tmp_path,
    )
    proxy = {"server": "http://proxy.test:8000", "username": "alice", "password": "topsecret"}
    with patch("linkedin_mcp.network.resolver.get_proxy_dict_for_profile", return_value=proxy):
        route = NetworkRouteResolver(settings).resolve(_profile())
    rendered = repr(route)
    assert "alice" not in rendered
    assert "topsecret" not in rendered
    assert route.as_browser_proxy() == proxy
