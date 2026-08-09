"""Chromium launch arguments for stealth browser configuration.

These flags reduce automation fingerprinting and improve headless stability.
They disable features that leak automation (sync, translate, cloud import)
and enable performance-oriented settings (async DNS, TCP fast open).

Reference: https://github.com/GoogleChrome/chrome-launcher/blob/master/docs/chrome-flags-for-tools.md
"""

# Comprehensive stealth args for Chromium launch.
# These args are applied to every browser instance regardless of platform.
STEALTH_ARGS: list[str] = [
    # ── WebRTC / IP leak prevention ──
    "--disable-webrtc",
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    # Disable IPv6 to prevent IPv6 traffic bypassing IPv4-only proxies.
    # Without this, the browser may connect via IPv6 directly, leaking
    # the real IPv6 address and geographic location.
    "--disable-ipv6",

    # ── Critical anti-detection ──
    "--disable-blink-features=AutomationControlled",
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
    "--safebrowsing-disable-auto-update",
    "--metrics-recording-only",

    # ── UI / window ──
    "--start-maximized",
    "--window-position=0,0",
    "--mute-audio",
    "--autoplay-policy=user-gesture-required",
    "--disable-infobars",
    "--disable-notifications",
    "--hide-scrollbars",
    "--disable-logging",
    "--disable-prompt-on-repost",

    # ── Performance / stability ──
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-ipc-flooding-protection",
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
    "--ignore-gpu-blocklist",

    # ── Cookie / keychain ──
    "--disable-cookie-encryption",
    "--use-mock-keychain",

    # ── Misc ──
    "--disable-print-preview",
    "--disable-offer-upload-credit-cards",
    "--disable-offer-store-unmasked-wallet-cards",
    "--lang=en-US",
    "--accept-lang=en-US",
]

# Additional args only used when running inside Docker (Linux + headless).
DOCKER_ONLY_ARGS: list[str] = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
]


def get_stealth_args(headless: bool = False, is_docker: bool = False) -> list[str]:
    """Build the full list of stealth launch args for the current environment.

    Args:
        headless: Whether the browser will run in headless mode.
        is_docker: Whether the browser is running inside a Docker container.

    Returns:
        List of Chromium command-line arguments.
    """
    args = list(STEALTH_ARGS)
    if is_docker:
        args.extend(DOCKER_ONLY_ARGS)
    return args
