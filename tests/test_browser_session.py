import asyncio
import types
import sys
from dataclasses import dataclass
from typing import Any, Dict, List

import pytest

# Testing library & framework: pytest
# - Async tests use pytest.mark.asyncio if pytest-asyncio plugin is present.
# - We mock external dependencies (CDPClient, httpx, EventBus handlers).
# - We validate public interfaces and event-driven behaviors via direct handler calls.

# Attempt to import the module under test
# The snippet appears from browser_use.browser.session; adjust if module path differs in repo.
from browser_use.browser.session import BrowserSession, CDPSession

# --- Lightweight fakes/mocks ---

class FakeSenderDomain:
    def __init__(self, responses: Dict[str, Any] | None = None):
        self.responses = responses or {}
        self.calls: List[Dict[str, Any]] = []

    async def enable(self, **kwargs):
        self.calls.append({"method": "enable", "kwargs": kwargs})
        return self.responses.get("enable", {})

    async def setAutoAttach(self, params):
        self.calls.append({"method": "setAutoAttach", "params": params})
        return self.responses.get("setAutoAttach", {})

    async def attachToTarget(self, params):
        self.calls.append({"method": "attachToTarget", "params": params})
        # Provide a session id
        return {"sessionId": "sess-1", **self.responses.get("attachToTarget", {})}

    async def getTargets(self):
        self.calls.append({"method": "getTargets"})
        # Default empty set of targets
        return {"targetInfos": self.responses.get("getTargets", [])}

    async def getTargetInfo(self, params=None, session_id=None):
        self.calls.append({"method": "getTargetInfo", "params": params, "session_id": session_id})
        tid = (params or {}).get("targetId")
        # Default target info
        return {"targetInfo": {"targetId": tid, "url": "about:blank", "title": "About Blank"}}

    async def createTarget(self, params):
        self.calls.append({"method": "createTarget", "params": params})
        return {"targetId": "target-new"}

    async def closeTarget(self, params):
        self.calls.append({"method": "closeTarget", "params": params})
        return {}

    async def navigate(self, params=None, session_id=None):
        self.calls.append({"method": "navigate", "params": params, "session_id": session_id})
        return {"frameId": "frame-1"}

    async def runIfWaitingForDebugger(self, session_id=None):
        self.calls.append({"method": "runIfWaitingForDebugger", "session_id": session_id})
        return {}

    async def activateTarget(self, params=None):
        self.calls.append({"method": "activateTarget", "params": params})
        return {}

    async def evaluate(self, params=None, session_id=None):
        self.calls.append({"method": "evaluate", "params": params, "session_id": session_id})
        # Return 1+1=2 for health check
        return {"result": {"value": 2}}

    async def setGeolocationOverride(self, params=None):
        self.calls.append({"method": "setGeolocationOverride", "params": params or {}})
        return {}

    async def clearGeolocationOverride(self):
        self.calls.append({"method": "clearGeolocationOverride"})
        return {}

    async def addScriptToEvaluateOnNewDocument(self, params=None, session_id=None):
        self.calls.append({"method": "addScriptToEvaluateOnNewDocument", "params": params, "session_id": session_id})
        return {"identifier": "script-1"}

    async def removeScriptToEvaluateOnNewDocument(self, params=None, session_id=None):
        self.calls.append({"method": "removeScriptToEvaluateOnNewDocument", "params": params, "session_id": session_id})
        return {}

    async def setDeviceMetricsOverride(self, params=None):
        self.calls.append({"method": "setDeviceMetricsOverride", "params": params})
        return {}

    async def getFrameTree(self, session_id=None):
        self.calls.append({"method": "getFrameTree", "session_id": session_id})
        # Simple frame tree
        return {"frameTree": {"frame": {"id": "frame-1", "url": "about:blank"}}}

    async def getCookies(self, session_id=None):
        self.calls.append({"method": "getCookies", "session_id": session_id})
        return {"cookies": []}

    async def setCookies(self, params=None, session_id=None):
        self.calls.append({"method": "setCookies", "params": params, "session_id": session_id})
        return {}

    async def clearCookies(self, session_id=None):
        self.calls.append({"method": "clearCookies", "session_id": session_id})
        return {}

class FakeSender:
    """Mimics cdp_client.send with dynamic domains and register.* handlers."""
    def __init__(self, domain_overrides: Dict[str, FakeSenderDomain] | None = None, targets: List[Dict[str, Any]] | None = None):
        self.Page = domain_overrides.get("Page", FakeSenderDomain()) if domain_overrides else FakeSenderDomain()
        self.DOM = domain_overrides.get("DOM", FakeSenderDomain()) if domain_overrides else FakeSenderDomain()
        self.DOMSnapshot = domain_overrides.get("DOMSnapshot", FakeSenderDomain()) if domain_overrides else FakeSenderDomain()
        self.Accessibility = domain_overrides.get("Accessibility", FakeSenderDomain()) if domain_overrides else FakeSenderDomain()
        self.Runtime = domain_overrides.get("Runtime", FakeSenderDomain()) if domain_overrides else FakeSenderDomain()
        self.Debugger = domain_overrides.get("Debugger", FakeSenderDomain()) if domain_overrides else FakeSenderDomain()
        self.Target = domain_overrides.get("Target", FakeSenderDomain({"getTargets": targets or []})) if domain_overrides else FakeSenderDomain({"getTargets": targets or []})
        self.Browser = domain_overrides.get("Browser", FakeSenderDomain()) if domain_overrides else FakeSenderDomain()
        self.Emulation = domain_overrides.get("Emulation", FakeSenderDomain()) if domain_overrides else FakeSenderDomain()
        self.Storage = domain_overrides.get("Storage", FakeSenderDomain()) if domain_overrides else FakeSenderDomain()
        self.Fetch = domain_overrides.get("Fetch", FakeSenderDomain()) if domain_overrides else FakeSenderDomain()
        # register.*.* chain
        self.register = types.SimpleNamespace(
            Fetch=types.SimpleNamespace(
                authRequired=lambda handler: None,
                requestPaused=lambda handler: None,
            ),
            Target=types.SimpleNamespace(
                attachedToTarget=lambda handler: None
            )
        )

class FakeCDPClient:
    """Minimal async CDP client used in tests. Has .send and .register, start/stop coroutines."""
    def __init__(self, url: str, targets: List[Dict[str, Any]] | None = None):
        self.url = url
        self.send = FakeSender(targets=targets)
        self.register = self.send.register
        self.started = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.started = False

# Utilities: fake is_new_tab_page for deterministic behavior
def fake_is_new_tab_page(url: str) -> bool:
    return url.startswith("chrome://newtab") or url.startswith("chrome://new-tab-page") or url == "about:blank"

@pytest.fixture(autouse=True)
def _patch_external(monkeypatch):
    """
    Auto-applied fixture to patch external dependencies inside the module under test:
    - CDPClient class replaced with FakeCDPClient
    - is_new_tab_page uses local deterministic function
    """
    import browser_use.browser.session as session_mod
    monkeypatch.setattr(session_mod, "CDPClient", FakeCDPClient)
    # Patch nested imports that the module itself does: 'from browser_use.utils import is_new_tab_page'
    import browser_use.utils as utils_mod
    monkeypatch.setattr(utils_mod, "is_new_tab_page", fake_is_new_tab_page)

    # Patch httpx.AsyncClient when connect() fetches ws URL from /json/version
    class _Resp:
        def __init__(self, data):
            self._data = data
        def json(self):
            return self._data

    class _FakeAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): return False
        async def get(self, url):
            # Return a websocket debugger URL for conversion
            return _Resp({"webSocketDebuggerUrl": "ws://converted/socket"})

    import browser_use.browser.session as sm
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    yield

# ---------- CDPSession tests ----------

@pytest.mark.asyncio
async def test_cdpsession_for_target_requires_url_when_new_socket(monkeypatch):
    client = FakeCDPClient("ws://root")
    with pytest.raises(ValueError):
        await CDPSession.for_target(client, target_id="target-1", new_socket=True, cdp_url=None)

@pytest.mark.asyncio
async def test_cdpsession_attach_enables_default_domains(monkeypatch):
    client = FakeCDPClient("ws://root")
    # Prepare attachToTarget response via FakeSenderDomain (handled automatically)
    sess = CDPSession(cdp_client=client, target_id="t-1", session_id="connecting")
    attached = await sess.attach()  # default domains
    assert attached.session_id == "sess-1"
    # Verify some common domains had enable called (by presence of recorded calls)
    assert isinstance(client.send.Page, FakeSenderDomain)
    # At least one of the domains should have recorded enable
    enabled_any = any(d.calls for d in [
        client.send.Page, client.send.DOM, client.send.DOMSnapshot,
        client.send.Accessibility, client.send.Runtime, client.send.Inspector if hasattr(client.send, "Inspector") else FakeSenderDomain()
    ])
    assert enabled_any

@pytest.mark.asyncio
async def test_cdpsession_disconnect_swallows_errors(monkeypatch):
    class ErrClient(FakeCDPClient):
        async def stop(self): raise RuntimeError("boom")
    client = ErrClient("ws://root")
    sess = CDPSession(cdp_client=client, target_id="t-1", session_id="s-1", owns_cdp_client=True)
    # Should not raise
    await sess.disconnect()

# ---------- BrowserSession unit tests focusing on public surface and handlers ----------

@pytest.mark.asyncio
async def test_browser_session_reset_clears_state():
    bs = BrowserSession()
    # Seed some private state
    bs._cdp_session_pool["abc"] = CDPSession(cdp_client=FakeCDPClient("ws://x"), target_id="abc", session_id="s")
    bs._cached_selector_map = {1: types.SimpleNamespace(node_name="DIV")}
    bs._downloaded_files = ["/tmp/file1"]
    bs.agent_focus = bs._cdp_session_pool["abc"]
    bs.cdp_url = "ws://root"
    await bs.reset()
    assert bs._cdp_session_pool == {}
    assert bs._cached_selector_map == {}
    assert bs._downloaded_files == []
    assert bs.agent_focus is None
    # is_local defaults True; cdp_url cleared
    assert bs.cdp_url is None

def test_is_valid_target_filters():
    # New tab should be allowed
    t_newtab = {"type": "page", "url": "about:blank"}
    assert BrowserSession._is_valid_target(t_newtab, include_about=True, include_pages=True) is True
    # chrome:// should be excluded by default
    t_chrome = {"type": "page", "url": "chrome://settings"}
    assert BrowserSession._is_valid_target(t_chrome, include_chrome=False, include_pages=True) is False
    # http allowed when include_http
    t_http = {"type": "page", "url": "https://example.com"}
    assert BrowserSession._is_valid_target(t_http, include_http=True, include_pages=True) is True
    # workers excluded by default
    t_worker = {"type": "service_worker", "url": "https://example.com/sw.js"}
    assert BrowserSession._is_valid_target(t_worker, include_workers=False) is False

@pytest.mark.asyncio
async def test_update_and_get_dom_element_by_index():
    bs = BrowserSession()
    node = types.SimpleNamespace(node_name="A", attributes={"href": "#"}, element_index=5)
    bs.update_cached_selector_map({5: node})
    found = await bs.get_dom_element_by_index(5)
    assert found is node
    not_found = await bs.get_dom_element_by_index(2)
    assert not_found is None

@pytest.mark.asyncio
async def test_download_tracking_event_handler():
    bs = BrowserSession()
    # Directly call the handler with a simple object
    @dataclass
    class Evt:
        file_name: str
        path: str
    await bs.on_FileDownloadedEvent(Evt(file_name="report.pdf", path="/dl/report.pdf"))
    assert bs.downloaded_files == ["/dl/report.pdf"]
    # Duplicate paths should not duplicate entries
    await bs.on_FileDownloadedEvent(Evt(file_name="report.pdf", path="/dl/report.pdf"))
    assert bs.downloaded_files == ["/dl/report.pdf"]
    # Missing path logs a warning and does not add
    await bs.on_FileDownloadedEvent(Evt(file_name="nope", path=""))
    assert bs.downloaded_files == ["/dl/report.pdf"]

@pytest.mark.asyncio
async def test_get_tabs_title_logic_with_chrome_and_newtab(monkeypatch):
    # Provide a target list: about:blank (newtab), chrome://page, https page with title via getTargetInfo
    targets = [
        {"targetId": "t1", "type": "page", "url": "about:blank"},
        {"targetId": "t2", "type": "page", "url": "chrome://extensions"},
        {"targetId": "t3", "type": "page", "url": "https://example.com"},
    ]
    bs = BrowserSession()
    bs._cdp_client_root = FakeCDPClient("ws://root", targets=targets)
    # agent_focus required for cdp_client property and session methods in some paths, but get_tabs uses cdp_client directly
    tabs = await bs.get_tabs()
    # Expect three TabInfo entries
    assert len(tabs) == 3
    # about:blank marked to ignore
    t1 = [t for t in tabs if t.target_id == "t1"][0]
    assert "ignore this tab" in t1.title
    # chrome:// uses URL as title if missing
    t2 = [t for t in tabs if t.target_id == "t2"][0]
    assert t2.title.startswith("chrome://")
    # https should have non-empty title (getTargetInfo default set above)
    t3 = [t for t in tabs if t.target_id == "t3"][0]
    assert t3.title != ""

@pytest.mark.asyncio
async def test_connect_converts_http_to_ws_and_initializes_focus(monkeypatch):
    # Start from http URL to force conversion using patched httpx.AsyncClient
    bs = BrowserSession(cdp_url="http://localhost:9222")
    # Provide CDP client to be injected after conversion (via fixture)
    await bs.connect()
    assert bs.cdp_url == "ws://converted/socket"
    assert bs._cdp_client_root is not None
    # agent_focus and session pool initialized
    assert bs.agent_focus is not None
    assert isinstance(bs._cdp_session_pool, dict)

@pytest.mark.asyncio
async def test_navigate_event_happy_path(monkeypatch, caplog):
    # Prepare a session with root client and existing focus
    targets = [{"targetId": "curr", "type": "page", "url": "about:blank"}]
    bs = BrowserSession()
    bs._cdp_client_root = FakeCDPClient("ws://root", targets=targets)
    # Create initial focus session and pool
    focus = await CDPSession.for_target(bs._cdp_client_root, "curr", new_socket=False)
    bs.agent_focus = focus
    bs._cdp_session_pool["curr"] = focus

    # Perform navigation via handler (simulate event dispatching higher layer)
    class Evt:
        def __init__(self, url, new_tab=False):
            self.url = url
            self.new_tab = new_tab
    await bs.on_NavigateToUrlEvent(Evt("https://example.com", new_tab=False))
    # Confirm navigate called on focus client's Page domain
    # We cannot access internal calls easily; assert that agent focus remains on 'curr'
    assert bs.agent_focus.target_id == "curr"

@pytest.mark.asyncio
async def test_close_tab_and_tab_closed_handlers_update_focus(monkeypatch):
    # Setup with two tabs: current and another
    targets = [
        {"targetId": "t1", "type": "page", "url": "https://a"},
        {"targetId": "t2", "type": "page", "url": "https://b"},
    ]
    bs = BrowserSession()
    bs._cdp_client_root = FakeCDPClient("ws://root", targets=targets)
    sess1 = await CDPSession.for_target(bs._cdp_client_root, "t1", new_socket=False)
    bs.agent_focus = sess1
    bs._cdp_session_pool["t1"] = sess1
    # Close current tab via CloseTabEvent then TabClosedEvent
    class CloseEvt:
        def __init__(self, target_id): self.target_id = target_id
    await bs.on_CloseTabEvent(CloseEvt("t1"))
    # Then process TabClosedEvent to switch focus
    class ClosedEvt:
        def __init__(self, target_id): self.target_id = target_id
    await bs.on_TabClosedEvent(ClosedEvt("t1"))
    # After closure, focus should be set to most recent page or newly created one
    assert bs.agent_focus is not None

@pytest.mark.asyncio
async def test_get_or_create_cdp_session_reuses_and_focuses(monkeypatch):
    targets = [
        {"targetId": "t1", "type": "page", "url": "https://a"},
        {"targetId": "t2", "type": "page", "url": "https://b"},
    ]
    bs = BrowserSession(cdp_url="ws://root")
    bs._cdp_client_root = FakeCDPClient("ws://root", targets=targets)
    # Seed focus on t1
    sess1 = await CDPSession.for_target(bs._cdp_client_root, "t1", new_socket=False)
    bs.agent_focus = sess1
    bs._cdp_session_pool["t1"] = sess1
    # Request session for t1 -> should reuse and keep focus
    s = await bs.get_or_create_cdp_session("t1", focus=True)
    assert s is sess1
    assert bs.agent_focus is sess1
    # Request new session for t2 with focus change
    s2 = await bs.get_or_create_cdp_session("t2", focus=True, new_socket=False)
    assert s2 is not None
    assert bs.agent_focus is s2
    assert "t2" in bs._cdp_session_pool

@pytest.mark.asyncio
async def test_storage_state_cookies_only_path():
    bs = BrowserSession()
    # Seed client root and focus session
    bs._cdp_client_root = FakeCDPClient("ws://root")
    focus = await CDPSession.for_target(bs._cdp_client_root, "t1", new_socket=False)
    bs.agent_focus = focus
    bs._cdp_session_pool["t1"] = focus
    st = await bs._cdp_get_storage_state()
    assert "cookies" in st and isinstance(st["cookies"], list)
    assert "origins" in st and st["origins"] == []

@pytest.mark.asyncio
async def test_geolocation_set_and_clear():
    bs = BrowserSession()
    bs._cdp_client_root = FakeCDPClient("ws://root")
    # No focus needed for these methods
    await bs._cdp_set_geolocation(37.77, -122.42, accuracy=42.0)
    await bs._cdp_clear_geolocation()

@pytest.mark.asyncio
async def test_add_remove_init_script_roundtrip():
    bs = BrowserSession()
    bs._cdp_client_root = FakeCDPClient("ws://root")
    focus = await CDPSession.for_target(bs._cdp_client_root, "t1", new_socket=False)
    bs.agent_focus = focus
    bs._cdp_session_pool["t1"] = focus
    ident = await bs._cdp_add_init_script("console.log('init')")
    assert ident == "script-1"
    await bs._cdp_remove_init_script(ident)

@pytest.mark.asyncio
async def test_remove_highlights_fallback_path(monkeypatch):
    # Force evaluate to raise in the first attempt to trigger fallback
    class EvalFailSenderDomain(FakeSenderDomain):
        async def evaluate(self, params=None, session_id=None):
            raise RuntimeError("eval failed")

    failing_sender = FakeSender(domain_overrides={"Runtime": EvalFailSenderDomain()})
    class FailingClient(FakeCDPClient):
        def __init__(self, url):
            super().__init__(url)
            self.send = failing_sender
            self.register = failing_sender.register

    import browser_use.browser.session as session_mod
    monkeypatch.setattr(session_mod, "CDPClient", FailingClient)

    bs = BrowserSession()
    bs._cdp_client_root = FailingClient("ws://root")
    focus = await CDPSession.for_target(bs._cdp_client_root, "t1", new_socket=False)
    bs.agent_focus = focus
    # Should not raise even though first path fails
    await bs.remove_highlights()
