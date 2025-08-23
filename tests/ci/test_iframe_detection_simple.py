"""
Test the iframe detection implementation.
"""

import sys
import os

# Add the project root to the path so we can import browser_use
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)


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
        print(f"Failed to import from browser_use.iframe_detection: {e}")
        # Try direct import approach
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
    except ImportError as e:
        print(f"Failed to import from iframe_patch: {e}")
        # Try direct import approach
        raise e
    
    assert enable_iframe_support is not None
    assert auto_patch_browser_use is not None
    
    print("✅ All iframe patch functions are properly defined")


if __name__ == "__main__":
    test_iframe_detection_structure()
    test_iframe_patch_functions()
    print("🎉 All tests passed!")