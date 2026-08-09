// Run this in Chrome DevTools (F12 > Console) on any page
// Copy the output JSON and use it with clone_fingerprint.py

(async function extractFingerprint() {
    const fp = {
        // Navigator properties
        user_agent: navigator.userAgent,
        platform: navigator.platform,
        hardware_concurrency: navigator.hardwareConcurrency,
        device_memory: navigator.deviceMemory || 8,
        languages: navigator.languages ? Array.from(navigator.languages) : ['en-US'],
        
        // Screen properties
        screen_width: screen.width,
        screen_height: screen.height,
        color_depth: screen.colorDepth,
        
        // WebGL properties
        webgl_vendor: '',
        webgl_renderer: '',
    };
    
    // Extract WebGL info
    try {
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
        if (gl) {
            const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
            if (debugInfo) {
                fp.webgl_vendor = gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL);
                fp.webgl_renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
            }
        }
    } catch (e) {
        console.error('WebGL extraction failed:', e);
    }
    
    // Output as JSON
    const json = JSON.stringify(fp, null, 2);
    console.log('\n=== FINGERPRINT DATA ===\n');
    console.log(json);
    console.log('\n=== COPY THE JSON ABOVE ===\n');
    
    // Also copy to clipboard if possible
    try {
        await navigator.clipboard.writeText(json);
        console.log('✓ Copied to clipboard!');
    } catch (e) {
        console.log('(Could not copy to clipboard - copy manually)');
    }
    
    return fp;
})();
