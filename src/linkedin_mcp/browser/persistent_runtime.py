"""Native persistent Chrome runtime with one profile directory per account."""

import fcntl
import json
import logging
import os
from pathlib import Path
from typing import Optional
from uuid import UUID

from patchright.async_api import BrowserContext, Page, Playwright, async_playwright

from linkedin_mcp.browser.stealth import BrowserConfig, StealthBrowser
from linkedin_mcp.config import Settings, get_settings


logger = logging.getLogger(__name__)


class ProfileInUseError(RuntimeError):
    """Another browser process owns the persistent profile directory."""


class PersistentChromeRuntime(StealthBrowser):
    """Chrome using its native identity and durable user-data directory."""

    def __init__(self, config: BrowserConfig, settings: Settings | None = None):
        super().__init__(config)
        self.settings = settings or get_settings()
        normalized_uuid = str(UUID(config.profile_id))
        root = self.settings.browser_profile_root.expanduser().resolve()
        self.profile_dir = (root / normalized_uuid).resolve()
        if self.profile_dir.parent != root:
            raise ValueError("Invalid browser profile path")
        self._initialization_marker = self.profile_dir / ".linkedin-mcp-initialized.json"
        # Chrome can leave a partially-created directory after a failed launch.
        # Only our atomic marker proves that the one-time state import completed.
        self.was_initialized = self._initialization_marker.is_file()
        self._lock_fd: Optional[int] = None

    def mark_initialized(self, metadata: dict | None = None) -> None:
        """Atomically record that native-profile initialization completed."""
        self.profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self._initialization_marker.with_suffix(".tmp")
        payload = {"profile_path_version": 1, **(metadata or {})}
        with temporary.open("w", encoding="utf-8") as marker:
            json.dump(payload, marker, sort_keys=True)
            marker.flush()
            os.fsync(marker.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, self._initialization_marker)
        self.was_initialized = True

    def _acquire_profile_lock(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.profile_dir, 0o700)
        lock_path = self.profile_dir / ".linkedin-mcp.lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise ProfileInUseError(f"Profile {self.config.profile_id} is already in use") from exc
        self._lock_fd = fd

    def _release_profile_lock(self) -> None:
        if self._lock_fd is None:
            return
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(self._lock_fd)
            self._lock_fd = None

    async def start(self) -> bool:
        if self._started:
            return True

        self._acquire_profile_lock()
        try:
            self._playwright = await async_playwright().start()
            args = ["--disable-dev-shm-usage"]
            if self.settings.browser_disable_sandbox:
                args.append("--no-sandbox")

            options = {
                "channel": self.settings.browser_channel,
                "headless": self.config.headless,
                "no_viewport": True,
                "locale": self.config.locale,
                "timezone_id": self.config.timezone,
                "args": args,
            }
            if self.config.proxy_server:
                proxy = {"server": self.config.proxy_server}
                if self.config.proxy_username:
                    proxy["username"] = self.config.proxy_username
                if self.config.proxy_password:
                    proxy["password"] = self.config.proxy_password
                options["proxy"] = proxy

            self._context = await self._playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                **options,
            )
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            self._started = True
            logger.info(
                "Native persistent Chrome started for profile %s",
                self.config.profile_id[:8],
            )
            return True
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        try:
            await super().stop()
        finally:
            self._release_profile_lock()

    def is_running(self) -> bool:
        return bool(self._started and self._context and self._page and not self._page.is_closed())

    async def get_storage_state(self) -> dict:
        if not self._context:
            raise RuntimeError("Browser not started")
        return await self._context.storage_state(indexed_db=True)
