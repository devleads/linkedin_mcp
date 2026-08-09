"""Session management for browser instances."""

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from linkedin_mcp.browser.stealth import StealthBrowser, BrowserConfig
from linkedin_mcp.models.profile import ProfileFingerprint
from linkedin_mcp.db import get_db
from linkedin_mcp.db.repository import ProfileRepository, CookieRepository, BrowserStateRepository
from linkedin_mcp.proxy import get_proxy_dict_for_profile, get_active_proxy_provider_name
from linkedin_mcp.proxy.ipfoxy import ProxyNotAvailableError as IPFoxyProxyNotAvailableError
from linkedin_mcp.proxy.oxylabs import ProxyNotAvailableError as OxylabsProxyNotAvailableError
from linkedin_mcp.proxy.apify import ProxyNotAvailableError as ApifyProxyNotAvailableError
from linkedin_mcp.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class BrowserSession:
    """Active browser session for a profile."""
    profile_uuid: str
    profile_db_id: int
    browser: StealthBrowser
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    
    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = datetime.utcnow()
    
    async def save_cookies(self) -> int:
        """Save browser cookies and storage state to database."""
        try:
            browser_cookies = await self.browser.get_cookies(
                ["https://www.linkedin.com"]
            )
            
            with get_db() as db:
                cookie_repo = CookieRepository(db)
                count = cookie_repo.set_from_playwright(self.profile_db_id, browser_cookies)
                
                # Also save full storage state (cookies + localStorage) to DB.
                # This replaces the old filesystem-based user_data_dir persistence.
                try:
                    storage_state = await self.browser.get_storage_state()
                    state_repo = BrowserStateRepository(db)
                    state_repo.save_state(self.profile_db_id, storage_state)
                    logger.info(f"[session] Saved storage state for profile {self.profile_uuid[:8]}...")
                except Exception as se:
                    logger.warning(f"[session] Failed to save storage state: {se}")
            
            logger.info(f"[session] Saved {count} cookies for profile {self.profile_uuid[:8]}...")
            return count
        except Exception as e:
            logger.error(f"[session] Failed to save cookies: {e}")
            return 0
    
    async def close(self, debug_delay: int = 0) -> None:
        """Close the browser session.
        
        Args:
            debug_delay: Seconds to wait before closing (for debugging)
        """
        if debug_delay > 0:
            logger.info(f"[session] Debug delay: keeping browser open for {debug_delay}s...")
            await asyncio.sleep(debug_delay)
        
        # Save cookies before closing
        await self.save_cookies()
        
        # Stop browser
        await self.browser.stop()
        logger.info(f"[session] Closed browser for profile {self.profile_uuid[:8]}...")


class SessionManager:
    """Manages browser sessions for multiple profiles.
    
    Each profile gets its own isolated browser session with:
    - Unique fingerprint
    - Country-specific proxy
    - Persistent cookies (stored in database)
    
    Sessions are cached and reused. After BROWSER_DEBUG_DELAY seconds of
    inactivity, sessions are automatically closed.
    """
    
    def __init__(self):
        self._sessions: dict[str, BrowserSession] = {}
        self._active_operations: dict[str, int] = {}
        self._operation_locks: dict[str, asyncio.Lock] = {}
        self._operation_owners: dict[str, Optional[asyncio.Task]] = {}
        self._operation_depths: dict[str, int] = {}
        self._persistent_sessions: set[str] = set()
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self.settings = get_settings()
    
    def _start_cleanup_task(self):
        """Start background task to clean up idle sessions."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _preflight_ipfoxy_http_proxy(
        self,
        proxy_server: str,
        proxy_username: Optional[str],
        proxy_password: Optional[str],
        timeout_seconds: int = 8,
    ) -> None:
        """Fail fast for invalid/mismatched IPFoxy HTTP proxy settings.

        This verifies the proxy endpoint speaks HTTP CONNECT and credentials are
        accepted before launching browser context.
        """
        parsed = urlparse(proxy_server)
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            raise IPFoxyProxyNotAvailableError(
                f"Invalid IPFoxy proxy endpoint: {proxy_server}"
            )

        reader = None
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout_seconds,
            )

            request_lines = [
                "CONNECT www.linkedin.com:443 HTTP/1.1",
                "Host: www.linkedin.com:443",
                "Proxy-Connection: Keep-Alive",
            ]
            if proxy_username and proxy_password:
                token = base64.b64encode(
                    f"{proxy_username}:{proxy_password}".encode("utf-8")
                ).decode("ascii")
                request_lines.append(f"Proxy-Authorization: Basic {token}")

            payload = "\r\n".join(request_lines) + "\r\n\r\n"
            writer.write(payload.encode("utf-8"))
            await writer.drain()

            raw = await asyncio.wait_for(reader.read(512), timeout=timeout_seconds)
            if not raw:
                raise IPFoxyProxyNotAvailableError(
                    "IPFoxy proxy preflight failed: endpoint returned empty response"
                )

            response_head = raw.decode("latin-1", errors="ignore")
            if not response_head.startswith("HTTP/"):
                raise IPFoxyProxyNotAvailableError(
                    "IPFoxy proxy protocol mismatch: configured as HTTP but endpoint does not "
                    "speak HTTP CONNECT. Switch this proxy to HTTP protocol in IPFoxy dashboard."
                )

            status_line = response_head.splitlines()[0] if response_head.splitlines() else "HTTP response missing status"
            if " 200 " in status_line:
                return
            if " 407 " in status_line:
                raise IPFoxyProxyNotAvailableError(
                    "IPFoxy proxy authentication failed (HTTP 407). Verify username/password "
                    "for this profile in profile_proxy_configs."
                )

            raise IPFoxyProxyNotAvailableError(
                f"IPFoxy proxy CONNECT failed: {status_line}"
            )
        except asyncio.TimeoutError:
            raise IPFoxyProxyNotAvailableError(
                "IPFoxy proxy preflight timed out. Endpoint unreachable or blocked."
            )
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
    
    async def _cleanup_loop(self):
        """Background task to close idle sessions."""
        while True:
            await asyncio.sleep(10)  # Check every 10 seconds
            try:
                await self._close_idle_sessions()
            except Exception as e:
                logger.error(f"[session] Error in cleanup loop: {e}")
    
    async def _close_idle_sessions(self):
        """Close sessions that have been idle too long."""
        # Use debug_delay if set, otherwise default to 5 minutes for production
        idle_timeout = self.settings.browser_debug_delay
        if idle_timeout <= 0:
            idle_timeout = 300  # 5 minutes default for production
        
        now = datetime.utcnow()
        to_close = []
        
        for profile_uuid, session in self._sessions.items():
            if self._active_operations.get(profile_uuid, 0) > 0:
                continue
            if profile_uuid in self._persistent_sessions:
                continue
            idle_seconds = (now - session.last_activity).total_seconds()
            if idle_seconds > idle_timeout:
                to_close.append(profile_uuid)
        
        for profile_uuid in to_close:
            logger.info(f"[session] Closing idle session for {profile_uuid[:8]}... (idle {idle_timeout}s)")
            await self.close_session(profile_uuid)

    @asynccontextmanager
    async def operation_guard(self, profile_uuid: str):
        """Serialize profile operations and prevent idle cleanup.

        Tools for the same profile share one browser page/context, so concurrent
        navigation would corrupt in-flight flows. The guard is re-entrant for the
        current asyncio task because some tools are wrapped by the dispatcher and
        also call the guard internally.
        """
        current_task = asyncio.current_task()
        if current_task is None:
            raise RuntimeError("operation_guard requires an active asyncio task")

        async with self._lock:
            operation_lock = self._operation_locks.get(profile_uuid)
            if operation_lock is None:
                operation_lock = asyncio.Lock()
                self._operation_locks[profile_uuid] = operation_lock

            is_reentrant = self._operation_owners.get(profile_uuid) is current_task
            if is_reentrant:
                self._operation_depths[profile_uuid] = self._operation_depths.get(profile_uuid, 0) + 1
                self._active_operations[profile_uuid] = self._active_operations.get(profile_uuid, 0) + 1

        acquired_lock = False
        if not is_reentrant:
            if operation_lock.locked():
                logger.info(f"[session] Waiting for active operation on profile {profile_uuid[:8]}...")
            await operation_lock.acquire()
            acquired_lock = True
            async with self._lock:
                self._operation_owners[profile_uuid] = current_task
                self._operation_depths[profile_uuid] = 1
                self._active_operations[profile_uuid] = self._active_operations.get(profile_uuid, 0) + 1

        keepalive_task: Optional[asyncio.Task] = None

        async def _keepalive_loop():
            while True:
                await asyncio.sleep(8)
                async with self._lock:
                    session = self._sessions.get(profile_uuid)
                    if session:
                        session.touch()

        try:
            if acquired_lock:
                keepalive_task = asyncio.create_task(_keepalive_loop())
            yield
        finally:
            if keepalive_task:
                keepalive_task.cancel()
                try:
                    await keepalive_task
                except asyncio.CancelledError:
                    pass

            async with self._lock:
                depth = self._operation_depths.get(profile_uuid, 0)
                if depth <= 1:
                    self._operation_depths.pop(profile_uuid, None)
                    self._operation_owners.pop(profile_uuid, None)
                    should_release_lock = acquired_lock
                else:
                    self._operation_depths[profile_uuid] = depth - 1
                    should_release_lock = False

                current = self._active_operations.get(profile_uuid, 0)
                if current <= 1:
                    self._active_operations.pop(profile_uuid, None)
                else:
                    self._active_operations[profile_uuid] = current - 1

            if should_release_lock:
                operation_lock.release()
    
    async def create_session(self, profile_uuid: str, force_new: bool = False) -> BrowserSession:
        """Get or create a browser session for a profile.
        
        Always ensures the returned session has a running browser.
        If an existing session's browser has closed, it will be cleaned up
        and a new session will be created.
        
        Args:
            profile_uuid: Profile UUID
            force_new: If True, always create a new session (close existing if any)
        
        Returns:
            BrowserSession with running browser
        """
        # Start cleanup task if not running
        self._start_cleanup_task()
        
        # Reuse same-profile sessions by default.
        # Only explicit force_new rotates the existing browser for that profile.
        isolate = force_new

        logger.info(
            f"[session] create_session called for {profile_uuid} "
            f"(isolate={isolate}, cfg.browser_isolate_sessions={self.settings.browser_isolate_sessions})"
        )
        
        async with self._lock:
            # Check if session already exists
            if profile_uuid in self._sessions:
                session = self._sessions[profile_uuid]
                
                # If isolation mode, close existing session first
                if isolate:
                    logger.info(f"[session] Isolation mode: closing existing session for {profile_uuid[:8]}...")
                    try:
                        await session.save_cookies()
                        await session.browser.stop()
                    except Exception as e:
                        logger.warning(f"[session] Error closing existing session: {e}")
                    del self._sessions[profile_uuid]
                elif session.browser.is_running():
                    # Reuse existing session (non-isolation mode)
                    logger.info(f"[session] Reusing existing session for {profile_uuid[:8]}...")
                    session.touch()
                    return session
                else:
                    # Browser died - clean up and recreate
                    logger.warning(f"[session] Browser closed for {profile_uuid[:8]}, recreating session...")
                    try:
                        await session.browser.close()
                    except Exception:
                        pass  # Browser already closed
                    del self._sessions[profile_uuid]
        
        # Load profile from database
        logger.info(f"[session] Loading profile from database...")
        with get_db() as db:
            profile_repo = ProfileRepository(db)
            profile = profile_repo.get_by_uuid(profile_uuid)
            
            if not profile:
                logger.error(f"[session] Profile {profile_uuid} not found in database")
                raise ValueError(f"Profile {profile_uuid} not found")
            
            logger.info(f"[session] Profile loaded: country={profile.country}, timezone={profile.timezone}")
            
            if not profile.fingerprint:
                logger.error(f"[session] Profile {profile_uuid} has no fingerprint")
                raise ValueError(f"Profile {profile_uuid} has no fingerprint")
            
            logger.info(f"[session] Fingerprint loaded from DB: platform={profile.fingerprint.platform}, "
                        f"screen={profile.fingerprint.screen_width}x{profile.fingerprint.screen_height}, "
                        f"webgl_vendor={profile.fingerprint.webgl_vendor[:30] if profile.fingerprint.webgl_vendor else 'None'}..., "
                        f"ua={profile.fingerprint.user_agent[:50]}...")
            
            # Get proxy configuration (only if country is set)
            proxy_server = None
            proxy_username = None
            proxy_password = None
            
            provider_name = get_active_proxy_provider_name()
            try:
                if provider_name == "ipfoxy":
                    logger.info(
                        f"[session] Getting ipfoxy proxy for profile={profile_uuid[:8]}..."
                    )
                    proxy_config = get_proxy_dict_for_profile(profile)
                    proxy_server = proxy_config["server"]
                    proxy_username = proxy_config["username"]
                    proxy_password = proxy_config["password"]

                    if proxy_server.startswith("http://") or proxy_server.startswith("https://"):
                        await self._preflight_ipfoxy_http_proxy(
                            proxy_server=proxy_server,
                            proxy_username=proxy_username,
                            proxy_password=proxy_password,
                        )
                    logger.info(f"[session] Proxy: {proxy_server} (ipfoxy dedicated)")
                elif provider_name == "apify":
                    logger.info(
                        f"[session] Getting apify proxy for country={profile.country}, "
                        f"state={profile.state}..."
                    )
                    proxy_config = get_proxy_dict_for_profile(profile)
                    proxy_server = proxy_config["server"]
                    proxy_username = proxy_config["username"]
                    proxy_password = proxy_config["password"]
                    logger.info(f"[session] Proxy: {proxy_server} (apify residential)")
                elif profile.country:
                    logger.info(
                        f"[session] Getting oxylabs proxy for country={profile.country}, "
                        f"state={profile.state}, city={getattr(profile, 'city', None)}, port={profile.proxy_port}..."
                    )
                    proxy_config = get_proxy_dict_for_profile(profile)
                    proxy_server = proxy_config["server"]
                    proxy_username = proxy_config["username"]
                    proxy_password = proxy_config["password"]
                    logger.info(f"[session] Proxy: {proxy_server} (oxylabs)")
                else:
                    logger.info(f"[session] No country set - running WITHOUT proxy")
            except (OxylabsProxyNotAvailableError, IPFoxyProxyNotAvailableError, ApifyProxyNotAvailableError) as e:
                logger.error(f"[session] Proxy config error: {e}")
                if self.settings.proxy_required:
                    raise
                logger.warning("[session] proxy_required=false, continuing without proxy")
            
            # Build fingerprint for browser
            fp = ProfileFingerprint(
                user_agent=profile.fingerprint.user_agent,
                platform=profile.fingerprint.platform,
                screen_width=profile.fingerprint.screen_width,
                screen_height=profile.fingerprint.screen_height,
                color_depth=profile.fingerprint.color_depth,
                hardware_concurrency=profile.fingerprint.hardware_concurrency,
                device_memory=profile.fingerprint.device_memory,
                languages=profile.fingerprint.languages,
                webgl_vendor=profile.fingerprint.webgl_vendor,
                webgl_renderer=profile.fingerprint.webgl_renderer,
            )
            
            # Build browser config (strictly isolated per profile)
            # Browser state (cookies + localStorage) is persisted in the database
            # via profile_browser_states table, not on disk.
            browser_config = BrowserConfig(
                profile_id=profile_uuid,
                fingerprint=fp,
                timezone=profile.timezone or "UTC",
                proxy_server=proxy_server,
                proxy_username=proxy_username,
                proxy_password=proxy_password,
                headless=self.settings.headless,
            )
            
            # Store profile db id for cookie operations
            profile_db_id = profile.id
            
            # Load cookies from database
            cookie_repo = CookieRepository(db)
            cookies = cookie_repo.to_playwright_format(profile_db_id)
            logger.info(f"[session] Loaded {len(cookies)} cookies from database")
            
            # Load full browser storage state (cookies + localStorage) from DB.
            # This replaces the old filesystem-based user_data_dir persistence.
            state_repo = BrowserStateRepository(db)
            stored_state = state_repo.get_state(profile_db_id)
            if stored_state:
                logger.info(f"[session] Loaded storage state from database "
                            f"({len(stored_state.get('cookies', []))} cookies, "
                            f"{len(stored_state.get('origins', []))} origins)")
            else:
                logger.info(f"[session] No stored browser state — starting fresh")
            
            # Check for li_at cookie
            li_at = next((c for c in cookies if c.get('name') == 'li_at'), None)
            if li_at:
                logger.info(f"[session] li_at cookie present (length={len(li_at.get('value', ''))})")
                # Pre-flight expiry check: skip browser launch if cookie is expired.
                expires = li_at.get('expires')
                if expires and expires > 0:
                    import time as _time
                    remaining = expires - _time.time()
                    if remaining < 0:
                        logger.error(
                            f"[session] li_at cookie EXPIRED {-remaining:.0f}s ago — "
                            "skipping browser launch. Re-authenticate the profile."
                        )
                        raise ValueError(
                            f"li_at cookie expired {-remaining:.0f}s ago — re-authentication required"
                        )
                    else:
                        logger.info(f"[session] li_at cookie valid, expires in {remaining / 3600:.1f}h")
            else:
                logger.warning(f"[session] No li_at cookie found - authentication will likely fail")
        
        # Create browser (outside db context)
        logger.info(f"[session] Starting browser...")
        browser = StealthBrowser(browser_config)
        await browser.start()
        logger.info(f"[session] Browser started successfully")
        
        # Inject stored cookies into browser
        if stored_state:
            # Restore full storage state (cookies + localStorage) from DB.
            await browser.set_storage_state(stored_state)
            logger.info(f"[session] Restored storage state from database")
        elif cookies:
            # Fallback: only restore cookies (legacy profiles without stored state)
            await browser.set_cookies(cookies)
            logger.info(f"[session] Injected {len(cookies)} cookies into browser")
        
        # Create session
        session = BrowserSession(
            profile_uuid=profile_uuid,
            profile_db_id=profile_db_id,
            browser=browser,
        )
        
        # Store in cache
        self._sessions[profile_uuid] = session
        
        logger.info(f"[session] Created session for profile {profile_uuid[:8]}...")
        return session

    def get_session(self, profile_uuid: str) -> Optional[BrowserSession]:
        """Return active session for profile UUID if browser is still running."""
        session = self._sessions.get(profile_uuid)
        if not session:
            return None

        if not session.browser.is_running():
            # Drop stale session entries so callers can create a fresh one.
            self._sessions.pop(profile_uuid, None)
            self._persistent_sessions.discard(profile_uuid)
            return None

        session.touch()
        return session

    async def set_persistent(self, profile_uuid: str, persistent: bool = True) -> bool:
        """Mark/unmark a profile session as persistent (not subject to idle cleanup)."""
        async with self._lock:
            session = self._sessions.get(profile_uuid)
            if not session or not session.browser.is_running():
                self._persistent_sessions.discard(profile_uuid)
                return False

            if persistent:
                self._persistent_sessions.add(profile_uuid)
            else:
                self._persistent_sessions.discard(profile_uuid)

            session.touch()
            return True

    def is_persistent(self, profile_uuid: str) -> bool:
        """Return whether profile session is pinned to stay open."""
        return profile_uuid in self._persistent_sessions
    
    async def close_session(self, profile_uuid: str, force: bool = False) -> bool:
        """Close a browser session and save cookies.
        
        Args:
            profile_uuid: Profile UUID
        
        Returns:
            True if session was closed, False if not found
        """
        async with self._lock:
            if not force and self._active_operations.get(profile_uuid, 0) > 0:
                logger.info(f"[session] Skip close for {profile_uuid[:8]}... (active operation)")
                return False

            session = self._sessions.get(profile_uuid)
            if not session:
                return False
            
            # Save cookies before closing
            await session.save_cookies()
            
            # Stop browser
            await session.browser.stop()
            
            # Remove from sessions
            del self._sessions[profile_uuid]
            self._persistent_sessions.discard(profile_uuid)
            
            logger.info(f"[session] Closed session for profile {profile_uuid[:8]}...")
            return True
    
    async def close_all(self) -> None:
        """Close all active sessions."""
        async with self._lock:
            for profile_uuid in list(self._sessions.keys()):
                session = self._sessions[profile_uuid]
                try:
                    await session.save_cookies()
                    await session.browser.stop()
                except Exception as e:
                    logger.error(f"[session] Error closing session {profile_uuid[:8]}: {e}")
            
            self._sessions.clear()
            self._persistent_sessions.clear()
            logger.info("[session] Closed all sessions")
    
    def list_sessions(self) -> list:
        """List all active session profile UUIDs."""
        return list(self._sessions.keys())


# Singleton instance
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get session manager singleton."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
