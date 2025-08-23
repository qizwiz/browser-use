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


# ---------- Tests for pure function ----------
def test_transform_coordinates_to_global_basic():
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)
    ctx = FrameContext(frame_id="main", target_id="t-main", dom_nodes={}, coordinate_offset=(100, 50))
    assert det.transform_coordinates_to_global((10, 5, 20, 10), ctx) == (110, 55, 20, 10)


def test_transform_coordinates_to_global_negative_offsets():
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)
    ctx = FrameContext(frame_id="if1", target_id="t1", dom_nodes={}, coordinate_offset=(-25, -40))
    assert det.transform_coordinates_to_global((30, 40, 5, 5), ctx) == (5, 0, 5, 5)


# ---------- Tests for get_element_by_index_with_iframe_support ----------
def test_get_element_by_index_main_frame_hit(monkeypatch):
    # Found in main frame -> should not enumerate frames
    elem = FakeElement(FakeRect(1, 2, 3, 4))
    sess = FakeBrowserSession(main_lookup={5: elem})
    det = SimpleIframeDetection(sess)

    called = {"enumerated": False}

    async def _never_called():
        called["enumerated"] = True
        return []

    monkeypatch.setattr(det, "_enumerate_all_frames", _never_called)

    result = arun(det.get_element_by_index_with_iframe_support(5))
    assert result is elem
    assert called["enumerated"] is False, "Should not enumerate frames when main-frame lookup succeeds"


def test_get_element_by_index_found_in_iframe_caches_cross_frame(monkeypatch):
    # Not in main; found in iframe -> cache cross-frame element and return it
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
    # Should have created a cross-frame entry starting at index 10000
    assert 10000 in det._cross_frame_elements
    cfe = det._cross_frame_elements[10000]
    assert cfe.element is target_elem
    assert cfe.frame_context is iframe_ctx
    assert cfe.original_index == 42
    assert cfe.cross_frame_index == 10000
    assert det._next_cross_frame_index == 10001


def test_get_element_by_index_not_found_anywhere(monkeypatch):
    sess = FakeBrowserSession(main_lookup={})
    det = SimpleIframeDetection(sess)

    async def _frames():
        # Only main frame, empty dom
        return [arun(det._get_main_frame_context())]

    monkeypatch.setattr(det, "_enumerate_all_frames", _frames)

    result = arun(det.get_element_by_index_with_iframe_support(999))
    assert result is None


# ---------- Tests for click_element_in_iframe ----------
def test_click_element_in_iframe_success_coordinates_and_dispatch():
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

    # Verify two mouse events with expected coordinates and type
    types = [call[1]["type"] for call in sess.cdp_client_calls if call[0] == "dispatchMouseEvent"]
    coords = [(call[1]["x"], call[1]["y"]) for call in sess.cdp_client_calls if call[0] == "dispatchMouseEvent"]
    assert types == ["mousePressed", "mouseReleased"]
    assert coords == [(120, 60), (120, 60)]


def test_click_element_in_iframe_missing_rect_graceful_failure():
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)
    ctx = FrameContext(frame_id="if-bad", target_id="bad", dom_nodes={}, coordinate_offset=(0, 0))
    elem = FakeElement(rect=None)
    cfe = CrossFrameElement(element=elem, frame_context=ctx, original_index=2, cross_frame_index=10002)

    ok = arun(det.click_element_in_iframe(cfe))
    assert ok is False


# ---------- Tests for frame enumeration and contexts ----------
def test_get_main_frame_context_uses_cached_selector_map():
    node = FakeElement(FakeRect(0, 0, 1, 1))
    sess = FakeBrowserSession(element_map={3: node}, main_lookup={})
    det = SimpleIframeDetection(sess)

    ctx = arun(det._get_main_frame_context())
    assert ctx.frame_id == "main"
    assert ctx.target_id == "main"
    assert ctx.dom_nodes.get(3) is node
    assert ctx.coordinate_offset == (0, 0)
    assert ctx.is_cross_origin is False


def test_get_iframe_context_happy_path(monkeypatch):
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)

    # Force known offset and dom-node mapping for the iframe
    async def _off(_tid: str) -> Tuple[int, int]:
        return (10, 20)

    async def _dom(_tid: str) -> Dict[int, Any]:
        return {7: FakeElement(FakeRect(1, 2, 3, 4))}

    monkeypatch.setattr(det, "_calculate_iframe_offset", _off)
    monkeypatch.setattr(det, "_get_iframe_dom_nodes", _dom)

    ctx = arun(det._get_iframe_context("target-123456"))
    assert ctx is not None
    assert ctx.frame_id.endswith("3456")  # last 4 chars used
    assert ctx.target_id == "target-123456"
    assert ctx.coordinate_offset == (10, 20)
    assert ctx.is_cross_origin is True
    assert ctx.parent_frame_id == "main"
    assert 7 in ctx.dom_nodes


def test_enumerate_all_frames_uses_domservice(monkeypatch):
    """
    Stubs browser_use.dom.service.DomService to return two iframe targets.
    Ensures _enumerate_all_frames returns main + both iframe contexts.
    """
    # Create a synthetic module tree: browser_use.dom.service with DomService
    service_mod = ModuleType("browser_use.dom.service")
    dom_pkg = sys.modules.get("browser_use.dom") or ModuleType("browser_use.dom")
    root_pkg = sys.modules.get("browser_use") or ModuleType("browser_use")
    sys.modules["browser_use"] = root_pkg
    sys.modules["browser_use.dom"] = dom_pkg
    sys.modules["browser_use.dom.service"] = service_mod

    class _Targets:
        def __init__(self) -> None:
            self.iframe_sessions = [{"targetId": "ABCD1234"}, {"targetId": "EFGH5678"}]

    class DomService:
        def __init__(self, _session: Any) -> None:
            self._session = _session

        async def __aenter__(self) -> "DomService":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def _get_targets_for_page(self) -> _Targets:
            return _Targets()

    setattr(service_mod, "DomService", DomService)

    # Prepare detector with predictable iframe context factory
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)

    async def _mk_ctx(tid: str) -> FrameContext:
        return FrameContext(
            frame_id=f"iframe_{tid[-4:]}",
            target_id=tid,
            dom_nodes={},
            coordinate_offset=(1, 2),
            is_cross_origin=True,
            parent_frame_id="main",
        )

    monkeypatch.setattr(det, "_get_iframe_context", _mk_ctx)

    contexts = arun(det._enumerate_all_frames())
    # Expect main + 2 iframe contexts
    assert len(contexts) == 3
    assert contexts[0].frame_id == "main"
    assert {c.frame_id for c in contexts[1:]} == {"iframe_1234", "iframe_5678"}


# ---------- IframeAwareController tests ----------
def test_controller_enhanced_get_element_by_index_delegates(monkeypatch):
    sess = FakeBrowserSession()
    ctrl = IframeAwareController(original_controller=None, browser_session=sess)

    # Stub detection call to return a specific object
    expected = FakeElement(FakeRect(0, 0, 1, 1))
    async def _getter(idx: int):
        assert idx == 77
        return expected

    monkeypatch.setattr(ctrl.iframe_detection, "get_element_by_index_with_iframe_support", _getter)
    res = arun(ctrl.enhanced_get_element_by_index(77))
    assert res is expected


def test_controller_enhanced_click_element_by_index_cross_frame_path(monkeypatch):
    sess = FakeBrowserSession()
    ctrl = IframeAwareController(original_controller=None, browser_session=sess)

    # Place a cross-frame element under the same index to exercise that path
    ctx = FrameContext(frame_id="iframe_X", target_id="X", dom_nodes={}, coordinate_offset=(3, 4), is_cross_origin=True)
    cfe = CrossFrameElement(element=FakeElement(FakeRect(1, 2, 10, 10)), frame_context=ctx, original_index=5, cross_frame_index=5)
    ctrl.iframe_detection._cross_frame_elements[5] = cfe

    # Make lookup return a non-None element for this index to pass the initial guard
    async def _getter(idx: int):
        return FakeElement(FakeRect(0, 0, 1, 1))

    monkeypatch.setattr(ctrl, "enhanced_get_element_by_index", _getter)

    called = {"clicked": False}
    async def _clicker(cf: CrossFrameElement) -> bool:
        called["clicked"] = True
        return True

    monkeypatch.setattr(ctrl.iframe_detection, "click_element_in_iframe", _clicker)

    ok = arun(ctrl.enhanced_click_element_by_index(5))
    assert ok is True
    assert called["clicked"] is True


def test_controller_enhanced_click_element_by_index_main_frame_fallback(monkeypatch):
    """
    When element is not in _cross_frame_elements under that index, controller returns True,
    representing a delegation to the original controller for main-frame clicks.
    """
    sess = FakeBrowserSession()
    ctrl = IframeAwareController(original_controller=None, browser_session=sess)

    async def _getter(idx: int):
        return FakeElement(FakeRect(0, 0, 1, 1))

    monkeypatch.setattr(ctrl, "enhanced_get_element_by_index", _getter)

    ok = arun(ctrl.enhanced_click_element_by_index(12345))
    assert ok is True


# ---------- Integration patch (non-executing shape/sanity) ----------
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
    # Patched methods should not be the same object as the original
    assert sess.get_dom_element_by_index is not _orig_get
    assert sess.get_element_by_index is sess.get_dom_element_by_index


# ---------- Edge / error handling ----------
def test_get_iframe_context_handles_internal_errors(monkeypatch, caplog):
    """
    If an exception is raised inside _get_iframe_context, the method should log and return None.
    """
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)

    async def _boom(_tid: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(det, "_calculate_iframe_offset", _boom)
    caplog.set_level(logging.ERROR)

    ctx = arun(det._get_iframe_context("target-err"))
    assert ctx is None
    assert any("Error getting iframe context" in rec.message for rec in caplog.records)


def test_enumerate_all_frames_error_fallback_to_main(monkeypatch, caplog):
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
        # We simulate by patching DomService import to throw, causing except branch in _enumerate_all_frames
        class RaisingModule(ModuleType):
            pass
        service_mod = ModuleType("browser_use.dom.service")
        def _fail_import(*a, **k):
            raise RuntimeError("import fail")
        # Craft a temporary module that will raise when attribute is accessed
        sys.modules["browser_use"] = ModuleType("browser_use")
        sys.modules["browser_use.dom"] = ModuleType("browser_use.dom")
        sys.modules["browser_use.dom.service"] = service_mod
        # Monkeypatch the function that will be imported to raise upon use
        # Instead, patch det._get_iframe_context to raise to trigger except
        monkeypatch.setattr(det, "_get_iframe_context", _boom)

        contexts = arun(det._enumerate_all_frames())
        # Fallback returns [main]
        assert isinstance(contexts, list) and len(contexts) == 1
        assert contexts[0].frame_id == "main"
        assert any("Error enumerating frames" in rec.message for rec in caplog.records)

# ---------- Additional coordinate transform edge cases ----------
def test_transform_coordinates_to_global_zero_offset_and_large_values():
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)
    ctx = FrameContext(frame_id="main", target_id="t-main", dom_nodes={}, coordinate_offset=(0, 0))
    # Very large coordinates should be added correctly without mutation of size
    assert det.transform_coordinates_to_global((10_000_000, 20_000_000, 1, 1), ctx) == (10_000_000, 20_000_000, 1, 1)

def test_transform_coordinates_to_global_mixed_signs():
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)
    ctx = FrameContext(frame_id="if2", target_id="t2", dom_nodes={}, coordinate_offset=(15, -10))
    assert det.transform_coordinates_to_global((5, 25, 2, 2), ctx) == (20, 15, 2, 2)

# ---------- Cross-frame element caching lifecycle ----------
def test_get_element_by_index_iframe_cached_index_is_reused(monkeypatch):
    """
    On repeated lookup of the same original index inside the same iframe context,
    ensure the next cross-frame index does not keep incrementing and the same cached
    CrossFrameElement is used.
    """
    elem = FakeElement(FakeRect(1, 1, 2, 2))
    iframe_ctx = FrameContext(
        frame_id="iframe_ZZZ9",
        target_id="target-ZZZ9",
        dom_nodes={21: elem},
        coordinate_offset=(3, 4),
        is_cross_origin=True,
        parent_frame_id="main",
    )
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)

    # First enumeration returns main + iframe_ctx
    async def _frames_first():
        return [arun(det._get_main_frame_context()), iframe_ctx]
    # Second enumeration should not be necessary if cache is used, but provide a safe default
    async def _frames_second():
        return [arun(det._get_main_frame_context()), iframe_ctx]

    calls = {"count": 0}
    async def _frames_wrapper():
        calls["count"] += 1
        return await (_frames_first() if calls["count"] == 1 else _frames_second())

    monkeypatch.setattr(det, "_enumerate_all_frames", _frames_wrapper)

    # First lookup populates cache
    res1 = arun(det.get_element_by_index_with_iframe_support(21))
    assert res1 is elem
    first_cfi_index = next(iter(det._cross_frame_elements.keys()))
    cfi1 = det._cross_frame_elements[first_cfi_index]

    # Second lookup should re-use the same CrossFrameElement and not allocate a new index
    res2 = arun(det.get_element_by_index_with_iframe_support(21))
    assert res2 is elem
    assert len(det._cross_frame_elements) == 1
    cfi2 = det._cross_frame_elements[first_cfi_index]
    assert cfi1 is cfi2
    # _enumerate_all_frames should have run at most twice (guarding against runaway calls)
    assert calls["count"] <= 2

def test_get_element_by_index_iframe_different_original_indices_allocate_new(monkeypatch):
    """Different original indices in iframe should allocate distinct cross-frame indices."""
    iframe_ctx = FrameContext(
        frame_id="iframe_QWER",
        target_id="target-QWER",
        dom_nodes={7: FakeElement(FakeRect(0,0,1,1)), 8: FakeElement(FakeRect(0,0,1,1))},
        coordinate_offset=(0, 0),
        is_cross_origin=True,
        parent_frame_id="main",
    )
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)

    async def _frames():
        return [arun(det._get_main_frame_context()), iframe_ctx]
    monkeypatch.setattr(det, "_enumerate_all_frames", _frames)

    _ = arun(det.get_element_by_index_with_iframe_support(7))
    _ = arun(det.get_element_by_index_with_iframe_support(8))

    assert len(det._cross_frame_elements) == 2
    idxs = sorted(det._cross_frame_elements.keys())
    assert idxs == list(range(idxs[0], idxs[0] + 2)), "Allocations should be contiguous and increasing"

# ---------- CDP mouse dispatch failure path and parameter assertions ----------
def test_click_element_in_iframe_includes_expected_parameters():
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)
    ctx = FrameContext(
        frame_id="iframe_PARAM",
        target_id="PARAM",
        dom_nodes={},
        coordinate_offset=(10, 10),
        is_cross_origin=True,
        parent_frame_id="main",
    )
    elem = FakeElement(FakeRect(0, 0, 10, 10))
    cfe = CrossFrameElement(element=elem, frame_context=ctx, original_index=3, cross_frame_index=10005)
    ok = arun(det.click_element_in_iframe(cfe))
    assert ok is True
    # Assert button/type included and call order
    calls = [c for c in sess.cdp_client_calls if c[0] == "dispatchMouseEvent"]
    assert [c[1]["type"] for c in calls] == ["mousePressed", "mouseReleased"]
    assert all("button" in c[1] for c in calls), "Mouse events should include a 'button' field"
    assert all(c[1]["x"] >= 10 and c[1]["y"] >= 10 for c in calls), "Global coords should be offset by (10,10)"

def test_click_element_in_iframe_cdp_failure_gracefully_returns_false():
    sess = FakeBrowserSession(cdp_raise_on="mousePressed")
    det = SimpleIframeDetection(sess)
    ctx = FrameContext(
        frame_id="iframe_FAIL",
        target_id="FAIL",
        dom_nodes={},
        coordinate_offset=(0, 0),
        is_cross_origin=True,
        parent_frame_id="main",
    )
    elem = FakeElement(FakeRect(2, 2, 4, 4))
    cfe = CrossFrameElement(element=elem, frame_context=ctx, original_index=9, cross_frame_index=10009)
    ok = arun(det.click_element_in_iframe(cfe))
    assert ok is False

# ---------- Iframe context derivation for short target IDs ----------
def test_get_iframe_context_short_target_id_suffix_handling(monkeypatch):
    """
    If target id shorter than 4 chars, frame_id suffixing should not crash.
    We assert it still produces a valid FrameContext.
    """
    sess = FakeBrowserSession()
    det = SimpleIframeDetection(sess)

    async def _off(_tid: str):
        return (1, 1)
    async def _dom(_tid: str):
        return {}

    monkeypatch.setattr(det, "_calculate_iframe_offset", _off)
    monkeypatch.setattr(det, "_get_iframe_dom_nodes", _dom)

    ctx = arun(det._get_iframe_context("xy"))
    assert ctx is not None
    assert ctx.target_id == "xy"
    assert isinstance(ctx.frame_id, str) and ctx.frame_id.startswith("iframe_")
    assert ctx.coordinate_offset == (1, 1)
    assert ctx.is_cross_origin is True
    assert ctx.parent_frame_id == "main"

# ---------- IframeAwareController extended behaviors ----------
def test_controller_enhanced_click_reuses_cached_cross_frame_then_succeeds(monkeypatch):
    sess = FakeBrowserSession()
    ctrl = IframeAwareController(original_controller=None, browser_session=sess)

    # Put a cross-frame entry into detection
    ctx = FrameContext(frame_id="iframe_CTR", target_id="CTR", dom_nodes={}, coordinate_offset=(0, 0), is_cross_origin=True)
    elem = FakeElement(FakeRect(5, 5, 10, 10))
    cfe = CrossFrameElement(element=elem, frame_context=ctx, original_index=11, cross_frame_index=11)
    ctrl.iframe_detection._cross_frame_elements[11] = cfe

    # Ensure enhanced_get_element_by_index returns non-None to pass guard
    async def _getter(idx: int):
        return elem
    monkeypatch.setattr(ctrl, "enhanced_get_element_by_index", _getter)

    # Click path: record that it's called
    called = {"n": 0}
    async def _click(cf: CrossFrameElement) -> bool:
        called["n"] += 1
        return True
    monkeypatch.setattr(ctrl.iframe_detection, "click_element_in_iframe", _click)

    ok = arun(ctrl.enhanced_click_element_by_index(11))
    assert ok is True and called["n"] == 1

def test_controller_enhanced_click_cross_frame_click_failure_bubbles_false(monkeypatch):
    sess = FakeBrowserSession()
    ctrl = IframeAwareController(original_controller=None, browser_session=sess)
    ctx = FrameContext(frame_id="iframe_BAD", target_id="BAD", dom_nodes={}, coordinate_offset=(0, 0), is_cross_origin=True)
    elem = FakeElement(FakeRect(0, 0, 1, 1))
    cfe = CrossFrameElement(element=elem, frame_context=ctx, original_index=13, cross_frame_index=13)
    ctrl.iframe_detection._cross_frame_elements[13] = cfe

    async def _getter(idx: int):
        return elem
    monkeypatch.setattr(ctrl, "enhanced_get_element_by_index", _getter)

    async def _click_fail(cf: CrossFrameElement) -> bool:
        return False
    monkeypatch.setattr(ctrl.iframe_detection, "click_element_in_iframe", _click_fail)

    ok = arun(ctrl.enhanced_click_element_by_index(13))
    assert ok is False

# ---------- Patch integration defensive checks ----------
def test_patch_browser_use_with_iframe_support_idempotent_patch_application(monkeypatch):
    """
    Applying the patch twice should still yield a working detector and keep methods present.
    This guards against double-patching in integrators.
    """
    async def _orig_get(idx: int):
        return None

    sess = FakeBrowserSession()
    setattr(sess, "get_dom_element_by_index", _orig_get)

    detector1 = patch_browser_use_with_iframe_support(sess)
    detector2 = patch_browser_use_with_iframe_support(sess)
    # Both detectors should be SimpleIframeDetection instances
    assert isinstance(detector1, SimpleIframeDetection)
    assert isinstance(detector2, SimpleIframeDetection)
    # Methods should still be available and callable
    assert hasattr(sess, "get_dom_element_by_index")
    assert hasattr(sess, "get_element_by_index")

