"""Unit tests for browser stealth args and init scripts."""

import pytest

from linkedin_mcp.browser.stealth_args import STEALTH_ARGS, DOCKER_ONLY_ARGS, get_stealth_args
from linkedin_mcp.browser.stealth_init import build_stealth_init_script


class TestStealthArgs:
    """Test Chromium stealth launch arguments."""

    def test_stealth_args_not_empty(self):
        """STEALTH_ARGS should contain many flags."""
        assert len(STEALTH_ARGS) >= 40

    def test_disable_ipv6_present(self):
        """Should include --disable-ipv6 to prevent IPv6 leaks."""
        assert "--disable-ipv6" in STEALTH_ARGS

    def test_disable_webrtc_present(self):
        """Should include WebRTC disabling flags."""
        assert "--disable-webrtc" in STEALTH_ARGS
        assert "--webrtc-ip-handling-policy=disable_non_proxied_udp" in STEALTH_ARGS

    def test_automation_controlled_disabled(self):
        """Should disable AutomationControlled blink feature."""
        assert any("--disable-blink-features=AutomationControlled" in a for a in STEALTH_ARGS)

    def test_no_test_type_flag(self):
        """Should NOT include --test-type flag (detection risk)."""
        assert "--test-type" not in STEALTH_ARGS
        assert not any("--test-type" in a for a in STEALTH_ARGS)

    def test_docker_only_args(self):
        """DOCKER_ONLY_ARGS should contain sandbox-disabling flags."""
        assert "--no-sandbox" in DOCKER_ONLY_ARGS
        assert "--disable-setuid-sandbox" in DOCKER_ONLY_ARGS
        assert "--disable-dev-shm-usage" in DOCKER_ONLY_ARGS
        assert "--disable-gpu" in DOCKER_ONLY_ARGS

    def test_docker_args_not_in_stealth(self):
        """Docker-only args should not be in base STEALTH_ARGS."""
        for arg in DOCKER_ONLY_ARGS:
            assert arg not in STEALTH_ARGS

    def test_get_stealth_args_non_docker(self):
        """Non-Docker mode should return only STEALTH_ARGS."""
        args = get_stealth_args(headless=False, is_docker=False)
        assert args == STEALTH_ARGS
        assert "--no-sandbox" not in args

    def test_get_stealth_args_docker(self):
        """Docker mode should include Docker-only args."""
        args = get_stealth_args(headless=False, is_docker=True)
        assert len(args) == len(STEALTH_ARGS) + len(DOCKER_ONLY_ARGS)
        assert "--no-sandbox" in args
        assert "--disable-gpu" in args

    def test_get_stealth_args_returns_copy(self):
        """Should return a copy, not the original list."""
        args1 = get_stealth_args()
        args2 = get_stealth_args()
        assert args1 == args2
        assert args1 is not args2


class TestStealthInitScript:
    """Test stealth init script generation."""

    def test_returns_string(self):
        """Should return a non-empty JavaScript string."""
        script = build_stealth_init_script()
        assert isinstance(script, str)
        assert len(script) > 100

    def test_contains_webdriver_patch(self):
        """Should patch navigator.webdriver."""
        script = build_stealth_init_script()
        assert "webdriver" in script
        assert "undefined" in script

    def test_contains_platform(self):
        """Should include the platform value."""
        script = build_stealth_init_script(platform="Win32")
        assert "Win32" in script

    def test_contains_webgl_vendor(self):
        """Should include the WebGL vendor string."""
        script = build_stealth_init_script(webgl_vendor="Google Inc. (Apple)")
        assert "Google Inc. (Apple)" in script

    def test_contains_webgl_renderer(self):
        """Should include the WebGL renderer string."""
        script = build_stealth_init_script(webgl_renderer="ANGLE Metal Renderer")
        assert "ANGLE Metal Renderer" in script

    def test_contains_webrtc_block(self):
        """Should block WebRTC to prevent IP leaks."""
        script = build_stealth_init_script()
        assert "RTCPeerConnection" in script
        assert "WebRTC disabled" in script

    def test_contains_canvas_noise(self):
        """Should add canvas fingerprint noise."""
        script = build_stealth_init_script()
        assert "toDataURL" in script

    def test_contains_plugins_patch(self):
        """Should patch navigator.plugins."""
        script = build_stealth_init_script()
        assert "plugins" in script

    def test_contains_chrome_object(self):
        """Should add window.chrome object."""
        script = build_stealth_init_script()
        assert "chrome" in script
        assert "runtime" in script

    def test_custom_values_embedded(self):
        """Custom platform/vendor/renderer should be embedded in script."""
        script = build_stealth_init_script(
            platform="Linux x86_64",
            webgl_vendor="Qualcomm",
            webgl_renderer="Adreno (TM) 740",
        )
        assert "Linux x86_64" in script
        assert "Qualcomm" in script
        assert "Adreno (TM) 740" in script

    def test_iife_wrapper(self):
        """Script should be wrapped in an IIFE."""
        script = build_stealth_init_script()
        assert "(function()" in script
        assert ")();" in script
