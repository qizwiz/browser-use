"""
Iframe Detection Patch for Browser-Use Issue #1700
===================================================

Simple integration that patches browser-use to support iframe element detection.
Based on S-expression analysis insights - much simpler than Mobile-Agent-v3.

Usage:
    from iframe_patch import enable_iframe_support
    
    # Enable iframe support for any browser-use session
    enable_iframe_support(browser_session)
    
    # Now iframe elements work automatically!
    element = await browser_session.get_element_by_index(123)  # ✅ Works in iframes
"""

import logging
from browser_use.iframe_detection import patch_browser_use_with_iframe_support

logger = logging.getLogger(__name__)


def enable_iframe_support(browser_session):
    """
    Enable iframe detection support for a Browser-Use session.
    
    Attempts to apply the iframe-detection patch to the provided browser session so the session
    can recognize and interact with iframe elements (fix for Issue #1700). On success returns
    the object produced by the patch operation; on failure the function logs the error and
    returns None instead of raising.
    
    Parameters:
        browser_session: an active BrowserSession instance to patch for iframe support.
    
    Returns:
        The patch/iframe_detection object returned by patch_browser_use_with_iframe_support on success,
        or None if patching failed.
    """
    try:
        iframe_detection = patch_browser_use_with_iframe_support(browser_session)
        logger.info("🎯 Iframe detection enabled - Issue #1700 solved!")
        return iframe_detection
    except Exception as e:
        logger.error(f"Failed to enable iframe support: {e}")
        return None


# Auto-patch for existing browser-use code (optional)
def auto_patch_browser_use():
    """
    Monkey-patch BrowserSession so newly created browser sessions automatically enable iframe detection.
    
    Replaces browser_use.browser.session.BrowserSession.__init__ with a wrapper that calls the original initializer
    and then calls enable_iframe_support(self). Intended for use when imported to enable iframe support transparently
    for all subsequently created BrowserSession instances. Failures are logged; the function does not raise.
    """
    try:
        # Import browser-use modules
        from browser_use.browser.session import BrowserSession
        
        # Store original session init
        original_init = BrowserSession.__init__
        
        # Create enhanced init
        def enhanced_init(self, *args, **kwargs):
            # Call original init
            """
            Wrapper for BrowserSession.__init__ that calls the original initializer and then enables iframe detection support.
            
            This function is intended to replace BrowserSession.__init__ via monkey-patching. It invokes the preserved original_init(self, *args, **kwargs) and afterwards calls enable_iframe_support(self) to attach iframe-aware detection to the newly initialized session.
            """
            original_init(self, *args, **kwargs)
            
            # Add iframe support automatically
            enable_iframe_support(self)
        
        # Replace init method
        BrowserSession.__init__ = enhanced_init
        
        logger.info("🚀 Browser-use auto-patched with iframe support!")
        
    except Exception as e:
        logger.error(f"Auto-patch failed: {e}")


if __name__ == "__main__":
    # Demo the patch
    print("🔧 Iframe detection patch ready!")
    print("Usage: enable_iframe_support(browser_session)")
    
    # Uncomment to auto-patch on import:
    # auto_patch_browser_use()