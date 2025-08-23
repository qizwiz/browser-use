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

logger = logging.getLogger(__name__)


def enable_iframe_support(browser_session):
    """
    Enable iframe support for a browser-use session.
    
    This is the main function that solves Issue #1700.
    """
    try:
        # Import inside function to allow mocking
        from browser_use.iframe_detection import patch_browser_use_with_iframe_support
        
        iframe_detection = patch_browser_use_with_iframe_support(browser_session)
        logger.info("Iframe detection enabled")
        return iframe_detection
    except Exception as e:
        logger.error("Failed to enable iframe support", exc_info=e)
        return None


# Auto-patch for existing browser-use code (optional)
from functools import wraps

def auto_patch_browser_use():
    """
    Automatically patch browser-use on import.
    
    This would make iframe detection work transparently.
    """
    try:
        # Import browser-use modules
        from browser_use.browser.session import BrowserSession

        # Idempotency guard
        if getattr(BrowserSession, "_iframe_init_patched", False):
            logger.info("ℹ️ BrowserSession.__init__ already auto-patched; skipping")
            return

        # Store original session init
        original_init = BrowserSession.__init__

        @wraps(original_init)
        def enhanced_init(self, *args, **kwargs):
            # Call original init
            original_init(self, *args, **kwargs)
            
            # Add iframe support automatically
            enable_iframe_support(self)
        
        # Replace init method
        BrowserSession.__init__ = enhanced_init
        BrowserSession._iframe_init_patched = True
        
        # Apply patch to any existing sessions (to verify it works)
        logger.info("auto-patched BrowserSession")
        
    except Exception as e:
        logger.error("Auto-patch failed", exc_info=e)

if __name__ == "__main__":
    # Demo the patch
    print("🔧 Iframe detection patch ready!")
    print("Usage: enable_iframe_support(browser_session)")
    
    # Uncomment to auto-patch on import:
    # auto_patch_browser_use()