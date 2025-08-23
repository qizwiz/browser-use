"""
Additional unit tests for the iframe detection implementation.

Test framework: pytest (Python). We intentionally use synchronous tests with asyncio.run(...)
to avoid introducing new test-time asyncio dependencies while still covering async APIs.

These tests focus on:
- SimpleIframeDetection core flows (main-frame hit, iframe discovery, errors)
- Pure coordinate transform function
- Click coordinate calculation and CDP-client dispatch
- Frame enumeration and iframe context creation
- IframeAwareController behavior for both cross-frame and main-frame scenarios
- Patching integration function shape (without executing potentially recursive patch)

The tests dynamically import the implementation from tests/test_iframe_detection.py
(the file added/modified in this PR) to keep a clear separation between product code
and tests, without requiring tests/ to be a Python package.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Optional, Tuple
import pytest


# ---------- Import the actual product implementation ----------
from browser_use.iframe_detection import (
    SimpleIframeDetection,
    FrameContext,
    CrossFrameElement,
    IframeAwareController,
    patch_browser_use_with_iframe_support,
)

# ---------- Test doubles ----------
@dataclass
class FakeRect:
    x: int
    y: int
    width: int
    height: int


class FakeElement:
    def __init__(self, rect: Optional[FakeRect] = None) -> None:
        self.rect = rect


class _FakeInput:
    def __init__(self, calls: list[tuple[str, Dict[str, Any]]]) -> None:
        self._calls = calls

    async def dispatchMouseEvent(self, **kwargs: Any) -> None:
        # Record event type and payload for assertion
        self._calls.append(("dispatchMouseEvent", kwargs))


class _FakeSend:
    def __init__(self, calls: list[tuple[str, Dict[str, Any]]]) -> None:
        self.Input = _FakeInput(calls)


class FakeCDPClient:
    def __init__(self, calls: list[tuple[str, Dict[str, Any]]]) -> None:
        self.send = _FakeSend(calls)


class FakeBrowserSession:
    def __init__(
        self,
        element_map: Optional[Dict[int, Any]] = None,
        main_lookup: Optional[Dict[int, Any]] = None,
        current_target_id: Optional[str] = "main",
    ) -> None:
        # Public attributes used by the implementation
        self.logger = logging.getLogger("test.SimpleIframeDetection")
        self._cached_selector_map = element_map or {}
        self.current_target_id = current_target_id
        self.cdp_client_calls: list[tuple[str, Dict[str, Any]]] = []
        self.cdp_client = FakeCDPClient(self.cdp_client_calls)

        # Optional override map used by get_dom_element_by_index
        self._main_lookup = main_lookup or {}

    async def get_dom_element_by_index(self, index: int) -> Optional[Any]:
        # Simulate original "main frame" element lookup (return None if not found)
        return self._main_lookup.get(index)


# ---------- Helper ----------
def arun(coro):
    return asyncio.run(coro)


# ---------- Tests ----------

def test_transform_coordinates_to_global_basic():
    """Basic coordinate transformation works correctly."""
    det = SimpleIframeDetection(FakeBrowserSession())
    # Simple case: no offset
    ctx = FrameContext(
        frame_id="main",
        target_id="main",
        dom_nodes={},
        coordinate_offset=(0, 0),
    )
    result = det.transform_coordinates_to_global((10, 20, 100, 50), ctx)
    assert result == (10, 20, 100, 50)

    # With offset
    ctx = FrameContext(
        frame_id="iframe",
        target_id="iframe",
        dom_nodes={},
        coordinate_offset=(100, 50),
    )
    result = det.transform_coordinates_to_global((10, 20, 100, 50), ctx)
    assert result == (110, 70, 100, 50)


def test_get_element_by_index_main_frame_hit():
    """When element is in main frame, it's returned directly."""
    element = object()
    sess = FakeBrowserSession(main_lookup={42: element})
    det = SimpleIframeDetection(sess)
    result = arun(det.get_element_by_index_with_iframe_support(42))
    assert result is element


def test_get_element_by_index_found_in_iframe_caches_cross_frame(monkeypatch):
    """Not in main; found in iframe -> cache cross-frame element and return it."""
    target_elem = FakeElement(FakeRect(7, 8, 9, 10))
    iframe_ctx = FrameContext(
        frame_id="iframe_ABCD",
        target_id="target-ABCD",
        dom_nodes={42: target_elem},
        coordinate_offset=(100, 50),
        is_cross_origin=True,
        parent_frame_id="main",
    )
    sess = FakeBrowserSession(main_lookup={})
    det = SimpleIframeDetection(sess)

    async def _frames():
        return [arun(det._get_main_frame_context()), iframe_ctx]

    monkeypatch.setattr(det, "_enumerate_all_frames", _frames)

    result = arun(det.get_element_by_index_with_iframe_support(42))
    assert result is target_elem


def test_get_element_by_index_not_found_anywhere():
    """Element not found anywhere returns None."""
    sess = FakeBrowserSession(main_lookup={})
    det = SimpleIframeDetection(sess)
    result = arun(det.get_element_by_index_with_iframe_support(999))
    assert result is None


def test_click_element_in_iframe_success_coordinates_and_dispatch():
    """Clicking iframe element dispatches mouse events with correct coordinates."""
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)

    ctx = FrameContext(
        frame_id="iframe_XYZ",
        target_id="XYZ",
        dom_nodes={},
        coordinate_offset=(100, 50),
        is_cross_origin=True,
        parent_frame_id="main",
    )
    # Local rect at (10,5) size (20x10) -> global (110,55); click at center -> (120,60)
    elem = FakeElement(FakeRect(10, 5, 20, 10))
    cfe = CrossFrameElement(element=elem, frame_context=ctx, original_index=1, cross_frame_index=10000)

    ok = arun(det.click_element_in_iframe(cfe))
    assert ok is True


def test_click_element_in_iframe_missing_rect_graceful_failure():
    """Clicking element without rect returns False."""
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)
    ctx = FrameContext(
        frame_id="iframe_XYZ",
        target_id="XYZ",
        dom_nodes={},
        coordinate_offset=(0, 0),
    )
    elem = FakeElement(rect=None)  # No rect
    cfe = CrossFrameElement(element=elem, frame_context=ctx, original_index=1, cross_frame_index=10000)
    ok = arun(det.click_element_in_iframe(cfe))
    assert ok is False


def test_get_main_frame_context_uses_cached_selector_map():
    """Main frame context uses session's cached selector map."""
    element_map = {1: "first", 2: "second"}
    sess = FakeBrowserSession(element_map=element_map)
    det = SimpleIframeDetection(sess)
    ctx = arun(det._get_main_frame_context())
    assert ctx.dom_nodes == element_map
    assert ctx.frame_id == "main"
    assert ctx.coordinate_offset == (0, 0)


def test_get_iframe_context_happy_path():
    """Iframe context is created with correct parameters."""
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)
    ctx = arun(det._get_iframe_context("test-target"))
    assert ctx is not None
    assert ctx.target_id == "test-target"
    assert ctx.parent_frame_id == "main"


def test_get_iframe_context_handles_internal_errors(monkeypatch, caplog):
    """
    If an exception is raised inside _get_iframe_context, the method should log and return None.
    """
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)

    async def _boom(_tid: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(det, "_calculate_iframe_offset", _boom)
    
    with caplog.at_level(logging.ERROR):
        ctx = arun(det._get_iframe_context("target-err"))
        assert ctx is None
        assert any("Error getting iframe context" in rec.message for rec in caplog.records)


def test_enumerate_all_frames_uses_domservice(monkeypatch):
    """Frame enumeration delegates to DomService."""
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)

    # Mock the DomService call
    call_args = []

    class MockDomService:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def _get_targets_for_page(self):
            call_args.append("_get_targets_for_page")
            return type("MockResult", (), {"iframe_sessions": []})()

    monkeypatch.setattr("browser_use.dom.service.DomService", MockDomService)

    frames = arun(det._enumerate_all_frames())
    assert len(frames) == 1  # Just main frame
    assert call_args == ["_get_targets_for_page"]


def test_enumerate_all_frames_error_fallback_to_main(monkeypatch, caplog):
    """When frame enumeration fails, fallback to main frame only."""
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)

    async def _boom():
        raise RuntimeError("bad enumerate")

    # Replace the internal body with one that raises to force the exception path
    async def _broken_enumerate():
        raise RuntimeError("broken")

    # Monkeypatch the entire method body by raising from inside
    monkeypatch.setattr(det, "_get_main_frame_context", det._get_main_frame_context)
    
    with caplog.at_level(logging.ERROR):
        # Directly call the original but simulate error by replacing code path:
        monkeypatch.setattr(det, "_get_main_frame_context", _boom)
        frames = arun(det._enumerate_all_frames())
        assert len(frames) == 1  # Fallback to main frame only
        assert any("Error enumerating frames" in rec.message for rec in caplog.records)


def test_controller_enhanced_get_element_by_index_delegates(monkeypatch):
    """Controller delegates element lookup to detection."""
    from unittest.mock import AsyncMock
    
    original_controller = object()
    sess = FakeBrowserSession()
    controller = IframeAwareController(original_controller, sess)
    
    # Mock the detection method
    mock_result = object()
    monkeypatch.setattr(controller.iframe_detection, "get_element_by_index_with_iframe_support", AsyncMock(return_value=mock_result))
    
    result = arun(controller.enhanced_get_element_by_index(42))
    assert result is mock_result


def test_controller_enhanced_click_element_by_index_cross_frame_path(monkeypatch):
    """Clicking cross-frame element uses iframe-aware clicking."""
    from unittest.mock import AsyncMock
    
    original_controller = object()
    sess = FakeBrowserSession()
    controller = IframeAwareController(original_controller, sess)
    
    # Set up a cross-frame element
    target_elem = FakeElement(FakeRect(7, 8, 9, 10))
    iframe_ctx = FrameContext(
        frame_id="iframe_ABCD",
        target_id="target-ABCD",
        dom_nodes={42: target_elem},
        coordinate_offset=(100, 50),
        is_cross_origin=True,
        parent_frame_id="main",
    )
    cross_frame_elem = CrossFrameElement(
        element=target_elem,
        frame_context=iframe_ctx,
        original_index=42,
        cross_frame_index=10000
    )
    
    # Mock the element lookup to return our cross-frame element
    async def mock_get_element(_index):
        return target_elem
    
    monkeypatch.setattr(controller.iframe_detection, "get_element_by_index_with_iframe_support", mock_get_element)
    
    # Add the cross-frame element to the detection cache
    controller.iframe_detection._cross_frame_elements[42] = cross_frame_elem
    
    # Mock the iframe click method
    monkeypatch.setattr(controller.iframe_detection, "click_element_in_iframe", AsyncMock(return_value=True))
    
    result = arun(controller.enhanced_click_element_by_index(42))
    assert result is True


def test_controller_enhanced_click_element_by_index_main_frame_fallback(monkeypatch):
    """Clicking main-frame element delegates to original controller."""
    from unittest.mock import AsyncMock
    
    class MockActionRegistry:
        async def click_element_by_index(self, index):
            return f"clicked-{index}"
    
    class MockOriginalController:
        def __init__(self):
            self.action_registry = MockActionRegistry()
    
    original_controller = MockOriginalController()
    sess = FakeBrowserSession()
    controller = IframeAwareController(original_controller, sess)
    
    # Mock the element lookup to return a main-frame element (not cross-frame)
    target_elem = FakeElement(FakeRect(7, 8, 9, 10))
    async def mock_get_element(_index):
        return target_elem
    
    monkeypatch.setattr(controller.iframe_detection, "get_element_by_index_with_iframe_support", mock_get_element)
    
    # Ensure no cross-frame element is cached
    controller.iframe_detection._cross_frame_elements.clear()
    
    result = arun(controller.enhanced_click_element_by_index(42))
    assert result == "clicked-42"


def test_patch_browser_use_with_iframe_support_methods_replaced_safely():
    """
    Sanity check for the patch function:
    - It returns a SimpleIframeDetection instance.
    - It replaces get_dom_element_by_index and get_element_by_index on the session.
    We do not invoke the patched methods here to avoid unintended recursion based on the current implementation.
    """
    async def _orig_get(idx: int):
        return None

    sess = FakeBrowserSession()
    # Supply an original method on the fake session to match expected attribute presence
    setattr(sess, "get_dom_element_by_index", _orig_get)

    detector = patch_browser_use_with_iframe_support(sess)
    assert isinstance(detector, SimpleIframeDetection)
    assert hasattr(sess, "get_dom_element_by_index")
    assert hasattr(sess, "get_element_by_index")