"""
Test the iframe detection implementation.
"""

import sys
import os

# Add the current directory to the path so we can import browser_use
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_iframe_detection_structure():
    """Test that iframe detection classes and methods are properly defined."""
    # Import the iframe detection module
    try:
        from browser_use.iframe_detection import (
            SimpleIframeDetection, 
            FrameContext, 
            CrossFrameElement,
            patch_browser_use_with_iframe_support,
            unpatch_browser_use
        )
    except ImportError as e:
        # If we can't import from the package, try direct import
        try:
            # Try to import directly from the file
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "iframe_detection", 
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                           "browser_use", "iframe_detection.py")
            )
            iframe_detection = importlib.util.module_from_spec(spec)
            sys.modules["iframe_detection"] = iframe_detection
            spec.loader.exec_module(iframe_detection)
            
            SimpleIframeDetection = iframe_detection.SimpleIframeDetection
            FrameContext = iframe_detection.FrameContext
            CrossFrameElement = iframe_detection.CrossFrameElement
            patch_browser_use_with_iframe_support = iframe_detection.patch_browser_use_with_iframe_support
            unpatch_browser_use = iframe_detection.unpatch_browser_use
        except Exception:
            # Re-raise the original import error
            raise e
    
    # Test that classes exist and have the expected structure
    assert SimpleIframeDetection is not None
    assert FrameContext is not None
    assert CrossFrameElement is not None
    
    # Test that integration functions exist
    assert patch_browser_use_with_iframe_support is not None
    assert unpatch_browser_use is not None
    
    # Test that SimpleIframeDetection has the expected methods
    methods = [
        'get_element_by_index_with_iframe_support',
        '_enumerate_all_frames',
        '_get_main_frame_context',
        '_get_iframe_context',
        '_calculate_iframe_offset',
        '_get_iframe_dom_nodes',
        'transform_coordinates_to_global',
        'click_element_in_iframe'
    ]
    
    for method in methods:
        assert hasattr(SimpleIframeDetection, method), f"Missing method: {method}"
    
    print("✅ All iframe detection classes and methods are properly defined")


def test_iframe_patch_functions():
    """Test that iframe patch functions are properly defined."""
    try:
        from iframe_patch import enable_iframe_support, auto_patch_browser_use
    except ImportError:
        # Try to import from the file directly
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "iframe_patch", 
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                       "iframe_patch.py")
        )
        iframe_patch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(iframe_patch)
        
        enable_iframe_support = iframe_patch.enable_iframe_support
        auto_patch_browser_use = iframe_patch.auto_patch_browser_use
    
    assert enable_iframe_support is not None
    assert auto_patch_browser_use is not None
    
    print("✅ All iframe patch functions are properly defined")


if __name__ == "__main__":
    test_iframe_detection_structure()
    test_iframe_patch_functions()
    print("🎉 All tests passed!")