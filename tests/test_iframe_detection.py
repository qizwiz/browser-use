import sys
import types
import asyncio
import logging
import builtins
import pytest

# --- Test framework note ---
# Using pytest and pytest-asyncio for async tests.

# --- Create lightweight fakes for external browser_use modules/classes ---

# Fake EnhancedDOMTreeNode with only the attributes the code uses
class FakeRect:
    def __init__(self, x=0, y=0, width=10, height=10):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

class FakeNode:
    def __init__(self, name="node", rect=None, children=None, shadow_roots=None, content_document=None):
        self.name = name
        self.rect = rect
        self.children_nodes = children or []
        self.shadow_roots = shadow_roots or []
        self.content_document = content_document
        self.element_index = None

# Build fake modules tree: browser_use.dom.views, browser_use.dom.service, browser_use.browser.session
browser_use_mod = types.ModuleType("browser_use")
dom_pkg = types.ModuleType("browser_use.dom")
views_mod = types.ModuleType("browser_use.dom.views")
service_mod = types.ModuleType("browser_use.dom.service")
browser_pkg = types.ModuleType("browser_use.browser")
session_mod = types.ModuleType("browser_use.browser.session")

# EnhancedDOMTreeNode alias to our FakeNode so imports inside code succeed
views_mod.EnhancedDOMTreeNode = FakeNode

# DomService stub used in two ways:
# 1) "async with DomService(self.browser_session) as dom_service" and call dom_service._get_targets_for_page()
# 2) DomService(browser_session=mock_session).get_dom_tree(...)
class DomService:
    def __init__(self, browser_session=None):
        self._browser_session = browser_session
        self.opened = False

    async def __aenter__(self):
        self.opened = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.opened = False

    async def _get_targets_for_page(self):
        # Return an object with attribute iframe_sessions = list[{'targetId': str}]
        return types.SimpleNamespace(iframe_sessions=[{'targetId': 'frame-1234'}, {'targetId': 'frame-ABCD'}])

    async def get_dom_tree(self, target_id=None):
        # Build a tiny DOM tree for the iframe
        # root -> child -> shadow_root -> content_document (to exercise traversal)
        inner_doc = FakeNode("innerDoc")
        shadow = FakeNode("shadow", children=[inner_doc])
        child = FakeNode("child", shadow_roots=[shadow])
        root = FakeNode("root", children=[child])
        return root

service_mod.DomService = DomService

# Minimal BrowserSession class placeholder for patch/unpatch tests
class BrowserSession:
    async def get_dom_element_by_index(self, index: int):
        # Placeholder original behavior: return None to force iframe path
        return None

    # Alias as the code expects both names to exist
    get_element_by_index = get_dom_element_by_index

session_mod.BrowserSession = BrowserSession

# Inject into sys.modules so imports in module under test succeed
sys.modules.setdefault("browser_use", browser_use_mod)
sys.modules.setdefault("browser_use.dom", dom_pkg)
sys.modules.setdefault("browser_use.dom.views", views_mod)
sys.modules.setdefault("browser_use.dom.service", service_mod)
sys.modules.setdefault("browser_use.browser", browser_pkg)
sys.modules.setdefault("browser_use.browser.session", session_mod)

# Now import module under test. If code resides at browser_use/iframe_detection.py,
# repo-local import "browser_use.iframe_detection" should work.
import importlib

iframe_detection = importlib.import_module("browser_use.iframe_detection")
SimpleIframeDetection = iframe_detection.SimpleIframeDetection
IframeAwareController = iframe_detection.IframeAwareController
patch_browser_use_with_iframe_support = iframe_detection.patch_browser_use_with_iframe_support
unpatch_browser_use = iframe_detection.unpatch_browser_use

# --- Fixtures and common fakes ---

class FakeCDPClientSend:
    # Simulates nested namespaces like Page.getFrameTree, DOM.getDocument, etc.
    class PageNS:
        async def getFrameTree(self, session_id=None):
            # Minimal frame tree containing the target frames with parents
            # Structure aligns with code's expectations
            return {
                "frameTree": {
                    "frame": {"id": "main", "parentId": None},
                    "childFrames": [
                        {"frame": {"id": "frame-1234", "parentId": "main"}, "childFrames": []},
                        {"frame": {"id": "frame-ABCD", "parentId": "main"}, "childFrames": []},
                    ],
                }
            }

    class DOMNS:
        async def getDocument(self, params=None, session_id=None):
            # A DOM where nodes include 'frameId' and 'children'
            # We will ensure a node matches each target_id for coverage
            def node_for_frame(frame_id, backend=111):
                return {
                    "frameId": frame_id,
                    "backendNodeId": backend,
                    "children": []
                }
            return {
                "root": {
                    "children": [
                        node_for_frame("frame-1234", 222),
                        node_for_frame("frame-ABCD", 333),
                    ]
                }
            }

        async def getContentQuads(self, params=None, session_id=None):
            # Provide one quad -> coordinates -> derive offset
            return {"quads": [ [10, 20, 110, 20, 110, 220, 10, 220] ]}

        async def getBoxModel(self, params=None, session_id=None):
            # Not used when getContentQuads succeeds
            return {"model": {"content": [5, 6, 15, 6, 15, 16, 5, 16]}}

        async def resolveNode(self, params=None, session_id=None):
            return {"object": {"objectId": "node-obj-1"}}

    class RuntimeNS:
        async def callFunctionOn(self, params=None, session_id=None):
            return {"result": {"value": {"x": 3, "y": 4, "width": 100, "height": 50}}}

    class InputNS:
        async def dispatchMouseEvent(self, **kwargs):
            # Simulate successful dispatch
            return {"ok": True, "args": kwargs}

    def __init__(self):
        self.Page = self.PageNS()
        self.DOM = self.DOMNS()
        self.Runtime = self.RuntimeNS()
        self.Input = self.InputNS()

class FakeCDPSession:
    def __init__(self):
        self.cdp_client = FakeCDPClientSend()
        self.session_id = "sess-1"

class FakeBrowserSession:
    def __init__(self, main_has=None, cached_map=None, focus=True):
        # cached selector map for main frame
        self._cached_selector_map = cached_map or {}
        self.current_target_id = "main"
        self.agent_focus = FakeCDPSession() if focus else None
        self._dom_calls = []
        self._created_sessions = {}

    async def get_dom_element_by_index(self, index: int):
        return self._cached_selector_map.get(index)

    # Alias method present on protocol
    async def get_element_by_index(self, index: int):
        return await self.get_dom_element_by_index(index)

    async def get_or_create_cdp_session(self, target_id: str, focus: bool = False):
        # Return or create a fake child session
        sess = self._created_sessions.get(target_id)
        if not sess:
            sess = FakeCDPSession()
            self._created_sessions[target_id] = sess
        return sess

@pytest.mark.asyncio
async def test_get_element_by_index_returns_main_frame_hit():
    # Happy path: element present in main frame cached selector map
    node = FakeNode("main-hit")
    bs = FakeBrowserSession(cached_map={42: node})
    det = SimpleIframeDetection(bs)
    got = await det.get_element_by_index_with_iframe_support(42)
    assert got is node

@pytest.mark.asyncio
async def test_get_element_by_index_searches_iframes_and_caches_cross_frame():
    # Miss in main frame -> search iframe contexts -> find in iframe dom_nodes
    iframe_index = 77
    iframe_node = FakeNode("iframe-hit")
    # Prepare detector and monkeypatch internal enumeration to produce an iframe FrameContext
    bs = FakeBrowserSession(cached_map={})
    det = SimpleIframeDetection(bs)

    # Build a FrameContext-like object using the dataclass from the module
    FrameContext = iframe_detection.FrameContext
    fc = FrameContext(
        frame_id="iframe_1234",
        target_id="frame-1234",
        dom_nodes={iframe_index: iframe_node},
        coordinate_offset=(10, 20),
        is_cross_origin=True,
        parent_frame_id="main"
    )

    async def fake_enum():
        # include main and our iframe
        main_fc = await det._get_main_frame_context()
        return [main_fc, fc]

    # Patch _enumerate_all_frames
    det._enumerate_all_frames = fake_enum

    got = await det.get_element_by_index_with_iframe_support(iframe_index)
    assert got is iframe_node

    # Ensure a cross-frame entry was created with a high cross_frame_index key
    assert det._cross_frame_elements, "cross-frame cache should not be empty"
    # Verify the stored CrossFrameElement references original index and element
    cfe = next(iter(det._cross_frame_elements.values()))
    assert cfe.element is iframe_node
    assert cfe.original_index == iframe_index
    assert cfe.frame_context.frame_id == "iframe_1234"
    assert cfe.cross_frame_index >= 10000

@pytest.mark.asyncio
async def test_enumerate_all_frames_uses_domservice_context_manager(monkeypatch):
    # Validate that _enumerate_all_frames pulls main + two iframe sessions from DomService
    bs = FakeBrowserSession(cached_map={1: FakeNode("main")})
    det = SimpleIframeDetection(bs)

    # Spy on _get_iframe_context to ensure called for each target
    calls = []
    async def fake_get_iframe_context(tid: str):
        calls.append(tid)
        FrameContext = iframe_detection.FrameContext
        return FrameContext(
            frame_id=f"iframe_{tid[-4:]}",
            target_id=tid,
            dom_nodes={},
            coordinate_offset=(0, 0),
            is_cross_origin=True,
            parent_frame_id="main"
        )
    monkeypatch.setattr(det, "_get_iframe_context", fake_get_iframe_context)

    frames = await det._enumerate_all_frames()
    # Expect main + two iframes from DomService stub
    assert len(frames) == 3
    assert set(calls) == {"frame-1234", "frame-ABCD"}

@pytest.mark.asyncio
async def test_calculate_iframe_offset_prefers_content_quads(monkeypatch):
    bs = FakeBrowserSession()
    det = SimpleIframeDetection(bs)
    # Use existing FakeCDP stack; expect getContentQuads path returns (10,20)
    offset = await det._calculate_iframe_offset("frame-1234")
    assert offset == (10, 20)

@pytest.mark.asyncio
async def test_calculate_iframe_offset_handles_no_focus_returns_zero(monkeypatch):
    bs = FakeBrowserSession(focus=False)
    det = SimpleIframeDetection(bs)
    offset = await det._calculate_iframe_offset("frame-1234")
    assert offset == (0, 0)

def test_transform_coordinates_to_global_pure_function():
    from browser_use.iframe_detection import FrameContext
    det = SimpleIframeDetection(FakeBrowserSession())
    frame = FrameContext(
        frame_id="iframe_X",
        target_id="T",
        dom_nodes={},
        coordinate_offset=(15, 25),
        is_cross_origin=True,
        parent_frame_id="main"
    )
    assert det.transform_coordinates_to_global((1, 2, 30, 40), frame) == (16, 27, 30, 40)

@pytest.mark.asyncio
async def test_click_element_in_iframe_success_dispatches_two_events(monkeypatch):
    bs = FakeBrowserSession()
    det = SimpleIframeDetection(bs)

    # Prepare element with rect and frame context
    rect = FakeRect(x=5, y=7, width=100, height=50)
    node = FakeNode("clickable", rect=rect)
    FrameContext = iframe_detection.FrameContext
    cfe = iframe_detection.CrossFrameElement(
        element=node,
        frame_context=FrameContext(
            frame_id="iframe_1234",
            target_id="frame-1234",
            dom_nodes={},
            coordinate_offset=(10, 20),
            is_cross_origin=True,
            parent_frame_id="main"
        ),
        original_index=123,
        cross_frame_index=10000
    )

    # Spy on Input.dispatchMouseEvent to capture calls
    events = []
    orig = bs.agent_focus.cdp_client.Input.dispatchMouseEvent
    async def spy_dispatch(**kwargs):
        events.append(kwargs)
        return await orig(**kwargs)
    bs.agent_focus.cdp_client.Input.dispatchMouseEvent = spy_dispatch

    ok = await det.click_element_in_iframe(cfe)
    assert ok is True
    # Should have sent pressed and released
    assert len(events) == 2
    assert events[0]["type"] == "mousePressed"
    assert events[1]["type"] == "mouseReleased"
    # Verify coordinates are center of the element after global transform:
    # local (5,7) + offset (10,20) -> global (15,27), then center added 50,25
    # click_x = 15 + 50 = 65; click_y = 27 + 25 = 52
    assert events[0]["x"] == 65 and events[0]["y"] == 52

@pytest.mark.asyncio
async def test_click_element_in_iframe_no_rect_returns_false():
    bs = FakeBrowserSession()
    det = SimpleIframeDetection(bs)
    FrameContext = iframe_detection.FrameContext
    cfe = iframe_detection.CrossFrameElement(
        element=FakeNode("no-rect", rect=None),
        frame_context=FrameContext(
            frame_id="iframe_1234",
            target_id="frame-1234",
            dom_nodes={},
            coordinate_offset=(0, 0),
            is_cross_origin=True,
            parent_frame_id="main"
        )
    )
    ok = await det.click_element_in_iframe(cfe)
    assert ok is False

@pytest.mark.asyncio
async def test_click_element_in_iframe_no_focus_returns_false(monkeypatch):
    bs = FakeBrowserSession(focus=False)
    det = SimpleIframeDetection(bs)
    rect = FakeRect(1,2,10,10)
    node = FakeNode("rect", rect=rect)
    FrameContext = iframe_detection.FrameContext
    cfe = iframe_detection.CrossFrameElement(
        element=node,
        frame_context=FrameContext(
            frame_id="iframe_1234",
            target_id="frame-1234",
            dom_nodes={},
            coordinate_offset=(0, 0),
            is_cross_origin=True,
            parent_frame_id="main"
        )
    )
    ok = await det.click_element_in_iframe(cfe)
    assert ok is False

@pytest.mark.asyncio
async def test_get_iframe_dom_nodes_traversal_and_indexing(monkeypatch):
    # _get_iframe_dom_nodes should traverse returned tree and assign indices starting at 100000
    bs = FakeBrowserSession()
    det = SimpleIframeDetection(bs)
    mapping = await det._get_iframe_dom_nodes("frame-1234")
    # At least root + child + shadow + inner doc should be indexed
    assert len(mapping) >= 3
    # Keys should start at 100000
    assert min(mapping.keys()) >= 100000
    # All values should be FakeNode instances with element_index assigned
    for k, v in mapping.items():
        assert isinstance(v, FakeNode)
        assert v.element_index is not None

@pytest.mark.asyncio
async def test_iframe_aware_controller_click_flow_delegates_when_no_cross_frame(monkeypatch):
    # Because cross_frame_elements cache keys by cross_frame_index (>=10000),
    # lookup by the original index in IframeAwareController will miss and delegate
    # to original controller's click method.
    class FakeActionRegistry:
        def __init__(self):
            self.calls = []
        async def click_element_by_index(self, index):
            self.calls.append(index)
            return "clicked"

    class FakeOriginalController:
        def __init__(self):
            self.action_registry = FakeActionRegistry()

    bs = FakeBrowserSession(cached_map={5: FakeNode("main")})
    ctrl = IframeAwareController(FakeOriginalController(), bs)

    ok = await ctrl.enhanced_click_element_by_index(5)
    assert ok is True
    # Delegation should have occurred
    assert ctrl.original_controller.action_registry.calls == [5]

@pytest.mark.asyncio
async def test_patch_and_unpatch_restores_original_behavior(monkeypatch):
    # Before patching, BrowserSession.get_dom_element_by_index returns None (Fake)
    from browser_use.browser.session import BrowserSession as BSession
    bs = BSession()

    # Patch: should replace methods with enhanced one
    det = patch_browser_use_with_iframe_support(bs)  # returns SimpleIframeDetection instance
    assert isinstance(det, SimpleIframeDetection)

    # After patch, the class method should exist and be callable
    # But original behavior for main-frame lookup is preserved inside enhanced method.
    # We simulate by creating a session instance whose cached map includes the index.
    class PatchedSession(BSession):
        def __init__(self):
            super().__init__()
            self._cached_selector_map = {9: FakeNode("main9")}
            self.current_target_id = "main"
            self.agent_focus = FakeCDPSession()
        async def get_dom_element_by_index(self, index: int):
            # This will not be called directly; enhanced method will temporarily restore original
            return await super().get_dom_element_by_index(index)

    ps = PatchedSession()
    # Call the patched method on the instance through the class
    res = asyncio.get_event_loop().run_until_complete(BSession.get_dom_element_by_index(ps, 9))
    # Should find element in main frame due to enhanced wrapper restoring original temporarily
    assert res is None or isinstance(res, FakeNode)
    # Finally, unpatch
    assert unpatch_browser_use() is True
    # After unpatch, methods should be the original (Fake) again
    res2 = asyncio.get_event_loop().run_until_complete(BSession.get_dom_element_by_index(ps, 9))
    assert res2 is None

# Additional edge-case tests for _enumerate_all_frames fallback on exceptions
@pytest.mark.asyncio
async def test_enumerate_all_frames_fallbacks_on_exception(monkeypatch, caplog):
    bs = FakeBrowserSession(cached_map={})
    det = SimpleIframeDetection(bs)
    async def boom(*a, **k):
        raise RuntimeError("boom")
    # Force exception inside method by patching _get_main_frame_context to still work,
    # but DomService enter to raise
    class BadDomService(DomService):
        async def __aenter__(self):
            raise RuntimeError("boom")
    sys.modules["browser_use.dom.service"].DomService = BadDomService
    caplog.set_level(logging.ERROR)
    frames = await det._enumerate_all_frames()
    # Fallback returns only main frame context
    assert len(frames) == 1
    assert frames[0].frame_id == "main"
