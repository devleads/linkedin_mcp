"""Stealth init scripts injected into the browser context.

These scripts patch browser APIs to hide automation signals that Patchright
does not handle at the binary level. They are injected via `add_init_script`
on the browser context BEFORE any page is created.

Patches applied:
- navigator.languages → ['en-US', 'en']
- navigator.platform → match fingerprint
- window.chrome → { runtime: {} }
- Permissions API → returns Notification.permission for 'notifications'
- WebGL → returns fake vendor/renderer strings
- Canvas → adds noise to toDataURL fingerprints
- WebRTC → disabled to prevent IP leakage through proxy
- Notification API → fix permission mismatch (prompt vs default)
"""


def build_stealth_init_script(
    platform: str = "MacIntel",
    webgl_vendor: str = "Intel Inc.",
    webgl_renderer: str = "Intel Iris OpenGL Engine",
) -> str:
    """Build the stealth init script for a given fingerprint.

    Args:
        platform: The navigator.platform value to report (e.g., "MacIntel", "Win32").
        webgl_vendor: The WebGL vendor string (UNMASKED_VENDOR_WEBGL, param 37445).
        webgl_renderer: The WebGL renderer string (UNMASKED_RENDERER_WEBGL, param 37446).

    Returns:
        JavaScript source code to inject as an init script.
    """
    return f"""
    (function() {{
        // Keep navigator.webdriver and navigator.plugins native. Patchright
        // plus --disable-blink-features=AutomationControlled provides the
        // correct webdriver value without creating an own property, while
        // Chrome's native PluginArray preserves its prototype and Plugin
        // entries. Replacing either surface is itself detectable.

        // ── navigator.languages ──
        try {{
            Object.defineProperty(navigator, 'languages', {{
                get: () => ['en-US', 'en'],
                configurable: true,
            }});
        }} catch(e) {{}}

        // ── navigator.platform → match fingerprint ──
        try {{
            Object.defineProperty(navigator, 'platform', {{
                get: () => '{platform}',
                configurable: true,
            }});
        }} catch(e) {{}}

        // ── window.chrome → {{ runtime: {{}} }} ──
        // Real Chrome has a window.chrome object; headless does not.
        try {{
            var win = window;
            win.chrome = win.chrome || {{ runtime: {{}} }};
        }} catch(e) {{}}

        // ── Permissions API fix ──
        // navigator.permissions.query returns: granted | denied | prompt
        // Notification.permission returns: granted | denied | default
        // Fix the mismatch so they don't contradict each other.
        try {{
            var origQuery = navigator.permissions.query;
            navigator.permissions.query = function(params) {{
                if (params.name === 'notifications') {{
                    return Promise.resolve({{ state: 'prompt' }});
                }}
                return origQuery.call(this, params);
            }};
        }} catch(e) {{}}

        // ── Notification API fix ──
        // Set permission to "default" (not "prompt") to match real Chrome.
        try {{
            if (typeof Notification === 'undefined') {{
                window.Notification = function() {{}};
                window.Notification.requestPermission = function() {{
                    return Promise.resolve('default');
                }};
            }}
            Object.defineProperty(window.Notification, 'permission', {{
                get: function() {{ return 'default'; }},
                configurable: true,
            }});
        }} catch(e) {{}}

        // ── WebGL vendor/renderer spoofing ──
        // Returns the profile's vendor/renderer strings to match the fingerprint.
        try {{
            var originalGetParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {{
                if (parameter === 37445) return '{webgl_vendor}';
                if (parameter === 37446) return '{webgl_renderer}';
                return originalGetParameter.call(this, parameter);
            }};
        }} catch(e) {{}}

        // ── Canvas fingerprint noise ──
        // Adds subtle noise to toDataURL() output so canvas fingerprints
        // are unique per session rather than identifying the GPU.
        try {{
            var originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function() {{
                var ctx = this.getContext('2d');
                if (ctx && this.width > 0 && this.height > 0) {{
                    var w = Math.min(this.width, 8);
                    var h = Math.min(this.height, 8);
                    var imageData = ctx.getImageData(0, 0, w, h);
                    for (var i = 0; i < imageData.data.length; i += 4) {{
                        imageData.data[i] = imageData.data[i] ^ 1;
                    }}
                    ctx.putImageData(imageData, 0, 0);
                }}
                return originalToDataURL.apply(this, arguments);
            }};
        }} catch(e) {{}}

        // ── WebRTC disabled ──
        // Prevents IP leakage through the proxy via WebRTC.
        try {{
            var blockedRtc = function() {{
                throw new Error('WebRTC disabled by stealth session');
            }};
            window.RTCPeerConnection = blockedRtc;
            window.webkitRTCPeerConnection = blockedRtc;
        }} catch(e) {{}}
    }})();
    """
