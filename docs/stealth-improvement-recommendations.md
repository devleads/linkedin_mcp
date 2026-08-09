# Stealth Mode Improvement Recommendations

Comparison of the LinkedIn MCP Server (`/Users/sp007/web/masterlabs/linkedin/mcp`) with the Waisabi Data Core (`/Users/sp007/web/waisabi/data/core`) stealth implementation.

---

## Architecture Overview

| Feature | LinkedIn MCP (current) | Waisabi Data Core |
|---|---|---|
| Browser engine | Patchright (Python) `1.58.2` | Patchright (Node.js) `1.61.1` |
| Headless mode | `headless=False` default, Xvfb in Docker | `headless=False` forced when Xvfb active |
| Xvfb / virtual display | Docker CMD starts Xvfb on `:99` | Entrypoint script, `DP_USE_XVFB=1` env var |
| Proxy | Oxylabs (mobile/residential) + IPFoxy (dedicated) | Apify residential (sticky sessions) |
| Fingerprint profiles | Per-profile DB-stored fingerprint (UA, platform, WebGL, screen) | Pool of 6 randomized desktop profiles (Chrome/Safari/Firefox on Mac/Win/Linux) |
| Stealth init scripts | Minimal (permissions/Notification fix only) | Full suite (webdriver, plugins, WebGL, canvas, WebRTC) but skippable |
| Chromium launch args | Minimal (4 args + 4 Docker-only) | 58 args (comprehensive anti-fingerprint) |
| Human behavior | `HumanBehavior` class: curved mouse paths, typing delays, scroll variance | `humanPause`, `humanMouseAndScroll`, `humanType` with jitter |
| Cloudflare handling | None | `waitForCloudflare()` with Turnstile checkbox clicking |
| Resource blocking | None | Route-based blocking of fonts, media, beacons, etc. (skippable) |
| Auth flow | Cookie injection from DB | Learned auth flow replay (JSON file with selectors, URLs) |
| Challenge detection | `challenge_lock.py` (checkpoint/captcha/authwall detection) | `EmailVerificationRequiredError`, `LoginRequiredError` |
| Navigation retry | None | `gotoWithRetry` with 3 retries on transient network errors |
| Session persistence | DB-stored cookies, per-profile browser state dir | Persistent context (`launchPersistentContext`) or per-run ephemeral |

---

## 1. Changes Required to Better Mimic a Real User

### A. Missing Chromium Anti-Fingerprint Launch Args (Critical)

The LinkedIn MCP launches with only 4 args (`--disable-webrtc`, `--webrtc-ip-handling-policy`, `--disable-infobars`, `--disable-notifications`). Waisabi uses 58 args that eliminate automation signals.

Key missing args to add to `stealth.py` `StealthBrowser.start()`:

```python
args = [
    # ── Existing ──
    "--disable-webrtc",
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--disable-infobars",
    "--disable-notifications",

    # ── Critical anti-detection ──
    "--disable-blink-features=AutomationControlled",  # removes navigator.webdriver
    "--disable-features=AudioServiceOutOfProcess,TranslateUI,BlinkGenPropertyTrees",
    "--enable-features=NetworkService,NetworkServiceInProcess,TrustTokens,TrustTokensAlwaysAllowIssuance",

    # ── Rendering fingerprint consistency ──
    "--force-color-profile=srgb",
    "--font-render-hinting=none",
    "--blink-settings=primaryHoverType=2,availableHoverTypes=2,primaryPointerType=4,availablePointerTypes=4",

    # ── Disable phone-home / background traffic ──
    "--disable-background-networking",
    "--disable-domain-reliability",
    "--disable-crash-reporter",
    "--disable-client-side-phishing-detection",
    "--disable-component-extensions-with-background-pages",
    "--disable-sync",
    "--disable-translate",
    "--disable-cloud-import",

    # ── UI / window ──
    "--start-maximized",
    "--window-position=0,0",
    "--mute-audio",
    "--autoplay-policy=user-gesture-required",

    # ── Performance / stability (Docker) ──
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-sandbox",           # Docker only
    "--disable-setuid-sandbox", # Docker only
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-ipc-flooding-protection",

    # ── Misc anti-fingerprint ──
    "--disable-cookie-encryption",
    "--use-mock-keychain",
    "--disable-print-preview",
    "--disable-prompt-on-repost",
    "--disable-offer-upload-credit-cards",
    "--disable-offer-store-unmasked-wallet-cards",
    "--safebrowsing-disable-auto-update",
    "--metrics-recording-only",
    "--disable-threaded-animation",
    "--disable-threaded-scrolling",
    "--enable-surface-synchronization",
    "--run-all-compositor-stages-before-draw",
    "--disable-layer-tree-host-memory-pressure",
    "--disable-image-animation-resync",
    "--disable-partial-raster",
    "--disable-gesture-typing",
    "--disable-checker-imaging",
    "--disable-wake-on-wifi",
    "--enable-async-dns",
    "--enable-tcp-fast-open",
    "--enable-web-bluetooth",
    "--aggressive-cache-discard",
    "--enable-simple-cache-backend",
    "--disable-new-content-rendering-timeout",
    "--prerender-from-omnibox=disabled",
    "--hide-scrollbars",
    "--disable-logging",
    "--disable-dev-shm-usage",
    "--ignore-gpu-blocklist",
    "--lang=en-US",
    "--accept-lang=en-US",
    "--test-type",
]
```

Reference: `@/Users/sp007/web/waisabi/data/core/src/shared/scraper/browser-session.ts:43-101`

### B. Fix Init Script Timing (Critical)

**Current bug**: In `stealth.py:128`, the page is created with `new_page()` **before** `_apply_fingerprint_overrides()` is called. Init scripts only apply to **future** pages, not the already-created one. The first page is unprotected.

**Fix**: Call `add_init_script()` on the context **before** creating any pages.

```python
# Current (broken):
self._context = await self._browser.new_context(**context_options)
self._page = await self._context.new_page()          # page created BEFORE init script
await self._apply_fingerprint_overrides()              # too late for first page

# Fixed:
self._context = await self._browser.new_context(**context_options)
await self._apply_fingerprint_overrides()              # init script added first
self._page = await self._context.new_page()            # page created after init script
```

Reference: `@/Users/sp007/web/waisabi/data/core/src/shared/scraper/browser-session.ts:591-596`

### C. Add `--disable-blink-features=AutomationControlled` (Critical)

This is the single most important launch arg. Without it, `navigator.webdriver` is `true` and LinkedIn's bot detection catches it immediately. Patchright patches this at the binary level, but the launch arg provides defense-in-depth.

### D. Expand Init Script with Full Stealth Overrides

Current init script only fixes the Notification/permissions API mismatch. Add the full suite from waisabi:

```javascript
// navigator.webdriver → undefined
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// navigator.languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

// navigator.plugins → fake array
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });

// navigator.platform → match fingerprint
Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' }); // or Win32

// window.chrome
win.chrome = win.chrome ?? { runtime: {} };

// WebGL vendor/renderer
WebGLRenderingContext.prototype.getParameter = function patchedGetParameter(param) {
    if (param === 37445) return 'Intel Inc.';
    if (param === 37446) return 'Intel Iris OpenGL Engine';
    return originalGetParameter.call(this, param);
};

// Canvas fingerprint noise
HTMLCanvasElement.prototype.toDataURL = function patchedToDataURL(...args) {
    const ctx = this.getContext('2d');
    if (ctx && this.width > 0 && this.height > 0) {
        const imageData = ctx.getImageData(0, 0, Math.min(this.width, 8), Math.min(this.height, 8));
        for (let i = 0; i < imageData.data.length; i += 4) {
            imageData.data[i] = imageData.data[i] ^ 1;
        }
        ctx.putImageData(imageData, 0, 0);
    }
    return originalToDataURL.apply(this, args);
};

// WebRTC disabled
win.RTCPeerConnection = function() { throw new Error('WebRTC disabled'); };
win.webkitRTCPeerConnection = win.RTCPeerConnection;
```

Reference: `@/Users/sp007/web/waisabi/data/core/src/shared/scraper/browser-session.ts:388-441`

**Note**: Waisabi has a `skipStealthInit` option because Patchright already patches these at the binary level, and `addInitScript` is detectable by Cloudflare (patchright issue #41). For LinkedIn (not Cloudflare), JS-level patches are safe and add defense-in-depth.

### E. Add Navigation Retry on Transient Errors

Waisabi has `gotoWithRetry` that retries on `ERR_TIMED_OUT`, `ERR_CONNECTION_RESET`, `ERR_PROXY_CONNECTION_FAILED`, etc. The LinkedIn MCP has no retry.

```python
GOTO_MAX_RETRIES = 3
GOTO_RETRY_DELAY_MS = 3000
NETWORK_ERROR_RE = re.compile(
    r"ERR_TIMED_OUT|ERR_CONNECTION_RESET|ERR_CONNECTION_REFUSED|"
    r"ERR_PROXY_CONNECTION_FAILED|ERR_TUNNEL_CONNECTION_FAILED|"
    r"ERR_NAME_NOT_RESOLVED|ERR_INTERNET_DISCONNECTED|ERR_SOCKET_NOT_CONNECTED",
    re.IGNORECASE,
)

async def goto_with_retry(page, url, wait_until="domcontentloaded", timeout=60000):
    for attempt in range(GOTO_MAX_RETRIES):
        try:
            return await page.goto(url, wait_until=wait_until, timeout=timeout)
        except Exception as e:
            if not NETWORK_ERROR_RE.search(str(e)) or attempt >= GOTO_MAX_RETRIES - 1:
                raise
            logger.warning(f"Navigation retry {attempt + 1}/{GOTO_MAX_RETRIES}: {str(e)[:120]}")
            await asyncio.sleep(GOTO_RETRY_DELAY_MS / 1000)
```

Reference: `@/Users/sp007/web/waisabi/data/core/src/shared/scraper/goto-with-retry.ts`

### F. Improve Xvfb Startup with Proper Entrypoint

Replace the single-line Docker CMD with a proper entrypoint script:

```bash
#!/bin/sh
set -e

if [ "${USE_XVFB:-1}" = "1" ]; then
  echo "[entrypoint] Starting Xvfb on display :99 (1920x1080x24)..."
  Xvfb :99 -screen 0 1920x1080x24 -ac -nolisten tcp &
  XVFB_PID=$!
  export DISPLAY=:99
  sleep 1
  if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    echo "[entrypoint] ERROR: Xvfb failed to start. Falling back to headless mode."
    unset DISPLAY
    export HEADLESS=true
  else
    echo "[entrypoint] Xvfb started (PID $XVFB_PID, DISPLAY=$DISPLAY)"
  fi
fi

exec uv run python -m linkedin_mcp.http_server
```

Reference: `@/Users/sp007/web/waisabi/data/core/docker-entrypoint.sh`

### G. Add `ignore_https_errors` and `java_script_enabled` to Context Options

```python
context_options = {
    "viewport": {"width": fp.screen_width, "height": fp.screen_height},
    "locale": self.config.locale,
    "timezone_id": self.config.timezone,
    "user_agent": fp.user_agent,
    "color_scheme": "light",
    "ignore_https_errors": True,    # add
    "java_script_enabled": True,     # add
    "is_mobile": False,              # add
    "has_touch": False,              # add
}
```

### H. Add Human-Like Typing (Character-by-Character)

Current implementation uses `page.type()` with a fixed delay. Waisabi types character-by-character with randomized per-key delays and occasional longer pauses:

```python
async def human_type(self, selector: str, text: str) -> bool:
    locator = self._page.locator(selector).first()
    await locator.click(delay=random.randint(40, 140))
    await locator.fill("")
    try:
        for char in text:
            await locator.press_sequentially(char, delay=random.randint(55, 185))
            if random.random() < 0.06:
                await self._page.wait_for_timeout(random.randint(200, 600))
    except Exception:
        await locator.fill(text)  # fallback
    return True
```

Reference: `@/Users/sp007/web/waisabi/data/core/src/shared/scraper/browser-session.ts:255-272`

### I. Add Idle Mouse Movement and Scroll Between Actions

```python
async def human_mouse_and_scroll(self) -> None:
    try:
        width = self._page.viewport_size["width"]
        height = self._page.viewport_size["height"]
        steps = random.randint(2, 4)
        for _ in range(steps):
            await self._page.mouse.move(
                random.randint(40, width - 40),
                random.randint(40, height - 40),
                steps=random.randint(3, 8),
            )
            await self._page.wait_for_timeout(random.randint(40, 160))
        if random.random() < 0.7:
            await self._page.mouse.wheel(0, random.randint(120, 520))
            await self._page.wait_for_timeout(random.randint(150, 500))
    except Exception:
        pass  # best-effort
```

Reference: `@/Users/sp007/web/waisabi/data/core/src/shared/scraper/browser-session.ts:232-248`

### J. Add Human Pause with Reading Simulation

```python
async def human_pause(self, min_ms: int, max_ms: int) -> None:
    delay = random.randint(min_ms, max_ms)
    if random.random() < 0.1:  # 10% chance of longer "reading" pause
        delay += random.randint(600, 1800)
    await self._page.wait_for_timeout(delay)
```

Reference: `@/Users/sp007/web/waisabi/data/core/src/shared/scraper/browser-session.ts:221-225`

---

## 2. Should We Add Apify Proxy as Another Option?

**Yes, as a complement, not a replacement.**

### Current proxy setup:
- **Oxylabs**: Mobile proxies (sticky ports, 10-min sessions) and residential (country/city targeting)
- **IPFoxy**: Dedicated residential proxies (per-profile host/port/credentials)

### Apify proxy strengths:
- Residential proxy pool with sticky sessions (~30 min, longer than Oxylabs' 10 min)
- Excellent Cloudflare bypass — residential IPs from real ISPs
- Country targeting with session persistence
- Simpler credential format: `groups-RESIDENTIAL,session-<id>,country-<CC>`

### For LinkedIn specifically:

**Pros:**
- LinkedIn uses its own bot detection (not Cloudflare), but residential IPs from real ISPs are harder to flag than datacenter IPs
- Longer sticky sessions (30 min vs 10 min) mean fewer IP changes mid-session, reducing suspicious IP rotation patterns
- Apify's proxy infrastructure is battle-tested for web scraping at scale
- Good fallback when Oxylabs/IPFoxy IPs get flagged

**Cons:**
- LinkedIn's detection is primarily cookie/session-based, not IP-based. A clean residential IP with bad cookies still gets challenged
- Oxylabs mobile proxies are already excellent for LinkedIn (mobile IPs are trusted more than residential by anti-bot systems)
- Adding another proxy provider increases operational complexity

**Recommendation:** Add Apify as a third proxy provider option (alongside `oxylabs` and `ipfoxy`). Use it as:
1. A fallback when Oxylabs/IPFoxy IPs get flagged
2. For specific profiles that need longer sticky sessions
3. For countries where Oxylabs coverage is weak

Implementation reference: `@/Users/sp007/web/waisabi/data/core/src/shared/scraper/proxy.ts`

Key design points from waisabi:
- `ProxyConfig` interface with `server`, `username`, `password`, `country`
- Session ID persistence in DB with 25-min max age
- `buildProxyForRun()` returns `undefined` when disabled
- Username token format: `groups-RESIDENTIAL,session-<id>,country-<CC>`

Config addition:
```python
# In config.py Settings:
proxy_provider: Literal["oxylabs", "ipfoxy", "apify"] = Field(default="oxylabs")
apify_proxy_password: str = Field(default="", description="Apify proxy password")
```

---

## 3. Improvements to Avoid LinkedIn Bot Detection

### High Priority

| # | Issue | Fix |
|---|---|---|
| 1 | Init script applied after page creation | Move `add_init_script` before `new_page()` |
| 2 | Missing `--disable-blink-features=AutomationControlled` | Add to launch args |
| 3 | Only 4 launch args (waisabi has 58) | Add comprehensive stealth args |
| 4 | No navigation retry on transient errors | Add `goto_with_retry()` |
| 5 | Fragile Xvfb startup | Use proper entrypoint script with error checking |

### Medium Priority

| # | Issue | Fix |
|---|---|---|
| 6 | Fixed-delay typing | Character-by-character typing with randomized delays |
| 7 | No idle mouse movement between actions | Add `human_mouse_and_scroll()` |
| 8 | No reading pause simulation | Add 10% chance of longer pause |
| 9 | Timezone not validated against proxy country | Add validation / auto-derive timezone from proxy country |
| 10 | No JS-level WebRTC blocking | Add `RTCPeerConnection` block to init script |

### Low Priority

| # | Issue | Fix |
|---|---|---|
| 11 | No resource blocking | Add route-based blocking (fonts, media, beacons) |
| 12 | No canvas fingerprint noise | Add `toDataURL` noise to init script |
| 13 | No `window.chrome` object | Add `win.chrome = { runtime: {} }` to init script |
| 14 | No `--start-maximized` | Add to launch args |

---

## 4. Other Recommendations

### A. Patchright Version Upgrade

LinkedIn MCP uses `patchright==1.58.2`, waisabi uses `patchright@1.61.1`. Upgrade to match — newer versions include improved stealth patches.

```toml
# pyproject.toml
"patchright==1.61.1",  # was 1.58.2
```

### B. Session Keepalive Improvement

The `_keepalive_loop` touches the session every 8 seconds. Consider adding periodic mouse movement or scroll during idle periods to simulate a real user reading a page, rather than just touching the timestamp.

### C. Cookie Expiry Pre-Flight Check

Before launching a browser session, check if `li_at` is expired. If so, skip session creation and return an error immediately, saving browser launch resources.

```python
# In session.py create_session(), after loading cookies:
li_at = next((c for c in cookies if c.get('name') == 'li_at'), None)
if li_at:
    expires = li_at.get('expires')
    if expires and expires > 0 and expires < time.time():
        raise SessionError(f"li_at cookie expired {int(time.time() - expires)}s ago")
```

### D. Proxy Preflight for Oxylabs

Waisabi has `_preflight_ipfoxy_http_proxy()` that verifies the proxy endpoint works before launching the browser. The LinkedIn MCP has this for IPFoxy but not for Oxylabs. Add a similar preflight for Oxylabs to fail fast on misconfigured proxies.

### E. Switch to `launchPersistentContext`

The LinkedIn MCP uses `chromium.launch()` + `new_context()` with manual cookie injection. Waisabi's persistent mode uses `launchPersistentContext` which preserves cookies, localStorage, and IndexedDB across runs without manual injection.

Benefits for LinkedIn:
- Preserves localStorage and IndexedDB (not just cookies)
- Maintains consistent browser profile fingerprint across sessions
- Reduces the "new browser" signal that LinkedIn detects when cookies are injected into a fresh context

```python
# Instead of:
self._browser = await self._playwright.chromium.launch(**launch_options)
self._context = await self._browser.new_context(**context_options)

# Use:
self._context = await self._playwright.chromium.launch_persistent_context(
    user_data_dir=self.config.user_data_dir,
    headless=self.config.headless,
    args=args,
    viewport={...},
    locale=...,
    timezone_id=...,
    user_agent=...,
    proxy=proxy_options,
)
```

Reference: `@/Users/sp007/web/waisabi/data/core/src/shared/scraper/browser-session.ts:555-570`

### F. Fingerprint Diversity

`ProfileFingerprint` defaults are static (`webgl_vendor="Google Inc."`, `webgl_renderer="ANGLE (Intel, Intel(R) UHD Graphics 630)"`). All profiles without custom fingerprints will have identical WebGL fingerprints.

Generate diverse fingerprints per profile:
- Different GPU vendors (Intel, NVIDIA, AMD)
- Different screen sizes (1920x1080, 1366x768, 1440x900, 2560x1440)
- Different hardware concurrency (4, 8, 12, 16)
- Different device memory (4, 8, 16)

### G. Rate Limiting Between Profiles

If multiple profiles are used from the same machine, add inter-profile delays to avoid simultaneous browser launches that could be detected by LinkedIn's device fingerprinting (same hardware, different accounts).

### H. Match Timezone to Proxy Country

Add validation that the profile timezone matches the proxy exit country. A US proxy with `Asia/Dubai` timezone is a red flag.

```python
COUNTRY_TIMEZONE_MAP = {
    "US": "America/New_York",
    "GB": "Europe/London",
    "AE": "Asia/Dubai",
    "SG": "Asia/Singapore",
    # ...
}

def validate_timezone_country(country: str, timezone: str) -> bool:
    expected = COUNTRY_TIMEZONE_MAP.get(country.upper())
    if expected and timezone != expected:
        logger.warning(f"Timezone mismatch: country={country} expects={expected} got={timezone}")
        return False
    return True
```

### I. Randomized Fingerprint Profiles (Like Waisabi)

Consider adding a pool of randomized desktop profiles (like waisabi's `browser-profiles.ts`) for non-persistent sessions, with matching UA + viewport + locale + timezone + platform:

```python
PROFILES = [
    BrowserProfile("Chrome/Mac", "Mozilla/5.0 (Macintosh; ...)", 1365, 768, "en-US", "America/New_York", "MacIntel"),
    BrowserProfile("Chrome/Windows", "Mozilla/5.0 (Windows NT 10.0; ...)", 1366, 768, "en-US", "America/Chicago", "Win32"),
    BrowserProfile("Safari/Mac", "Mozilla/5.0 (Macintosh; ...)", 1440, 822, "en-US", "America/Los_Angeles", "MacIntel"),
    # ...
]
```

Reference: `@/Users/sp007/web/waisabi/data/core/src/shared/scraper/browser-profiles.ts`

---

## Summary Priority Matrix

| Priority | Item | Effort | Impact |
|---|---|---|---|
| P0 | Fix init script timing (before page creation) | Low | Critical |
| P0 | Add `--disable-blink-features=AutomationControlled` | Low | Critical |
| P0 | Add comprehensive stealth launch args | Low | High |
| P0 | Upgrade Patchright to 1.61.1 | Low | High |
| P1 | Add navigation retry | Medium | High |
| P1 | Improve Xvfb entrypoint | Low | Medium |
| P1 | Add `ignore_https_errors` to context | Low | Medium |
| P1 | Character-by-character typing | Medium | Medium |
| P1 | Idle mouse movement between actions | Medium | Medium |
| P2 | Add Apify proxy provider | Medium | Medium |
| P2 | Switch to `launchPersistentContext` | Medium | High |
| P2 | Fingerprint diversity | Medium | Medium |
| P2 | Timezone/proxy country validation | Low | Medium |
| P2 | WebRTC JS-level blocking | Low | Low |
| P3 | Canvas fingerprint noise | Low | Low |
| P3 | Resource blocking | Low | Low |
| P3 | `window.chrome` object | Low | Low |
| P3 | Rate limiting between profiles | Low | Low |
