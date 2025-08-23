"""
Tests for iframe_patch module.

Framework: pytest
- Uses pytest fixtures: monkeypatch, caplog
- Avoids importing real 'browser_use' by injecting fakes into sys.modules prior to importing iframe_patch
"""

import sys
import types
import importlib
import builtins
import contextlib

import pytest


def make_fake_browser_use_modules(patch_func_behavior="return", return_value="IFRAME-OK", raise_exc=None):
    """
    Create and register fake 'browser_use' package structure in sys.modules:
      - browser_use (package)
      - browser_use.iframe_detection (module) with patch_browser_use_with_iframe_support
      - browser_use.browser (package)
      - browser_use.browser.session (module) with BrowserSession
    The behavior of 'patch_browser_use_with_iframe_support' can be:
      - "return": returns return_value
      - "raise": raises raise_exc
    """
    # Root package
    bu_pkg = types.ModuleType("browser_use")
    bu_pkg.__path__ = []  # mark as package

    # iframe_detection submodule
    iframe_detection = types.ModuleType("browser_use.iframe_detection")

    def _patch(browser_session):
        if patch_func_behavior == "raise":
            exc = raise_exc or RuntimeError("boom")
            raise exc
        return return_value

    iframe_detection.patch_browser_use_with_iframe_support = _patch

    # browser subpackage and session module
    browser_pkg = types.ModuleType("browser_use.browser")
    browser_pkg.__path__ = []

    session_mod = types.ModuleType("browser_use.browser.session")

    class BrowserSession:
        def __init__(self, *args, **kwargs):
            # simple side effect to verify original __init__ still runs
            self.inited = True
            self.args = args
            self.kwargs = kwargs

    session_mod.BrowserSession = BrowserSession

    # Register in sys.modules
    sys.modules["browser_use"] = bu_pkg
    sys.modules["browser_use.iframe_detection"] = iframe_detection
    sys.modules["browser_use.browser"] = browser_pkg
    sys.modules["browser_use.browser.session"] = session_mod

    return iframe_detection, session_mod


@contextlib.contextmanager
def isolated_import(module_name):
    """
    Import a module with a clean slate by removing it from sys.modules,
    yielding the freshly imported module, then restoring previous state.
    """
    saved = sys.modules.pop(module_name, None)
    try:
        mod = importlib.import_module(module_name)
        yield mod
    finally:
        if saved is not None:
            sys.modules[module_name] = saved
        else:
            sys.modules.pop(module_name, None)


def test_enable_iframe_support_success(monkeypatch, caplog):
    # Arrange: Provide fake browser_use modules before importing target
    fake_iframe_mod, _ = make_fake_browser_use_modules(
        patch_func_behavior="return", return_value={"status": "ok", "patched": True}
    )

    # Fresh import of target after fakes are in place
    with isolated_import("iframe_patch") as iframe_patch:
        caplog.clear()
        caplog.set_level("INFO")

        dummy_session = object()

        # Act
        result = iframe_patch.enable_iframe_support(dummy_session)

        # Assert
        assert result == {"status": "ok", "patched": True}
        assert any("Iframe detection enabled" in rec.message for rec in caplog.records), \
            "Expected INFO log confirming iframe detection was enabled."


def test_enable_iframe_support_failure_logs_and_returns_none(monkeypatch, caplog):
    # Arrange: Make patch function raise
    make_fake_browser_use_modules(patch_func_behavior="raise", raise_exc=ValueError("bad session"))

    with isolated_import("iframe_patch") as iframe_patch:
        caplog.clear()
        caplog.set_level("ERROR")

        # Act
        result = iframe_patch.enable_iframe_support(browser_session=None)

        # Assert
        assert result is None
        assert any("Failed to enable iframe support" in rec.message for rec in caplog.records), \
            "Expected ERROR log when enabling iframe support fails."


def test_auto_patch_browser_use_replaces_init_and_invokes_enable(monkeypatch, caplog):
    # Arrange: Install fakes and import module
    _, fake_session_mod = make_fake_browser_use_modules()

    with isolated_import("iframe_patch") as iframe_patch:
        # Spy on enable_iframe_support
        calls = []

        def fake_enable(self):
            calls.append(self)

        monkeypatch.setattr(iframe_patch, "enable_iframe_support", fake_enable, raising=True)

        # Keep a handle to the original __init__ to compare later
        Original = fake_session_mod.BrowserSession.__init__

        caplog.clear()
        caplog.set_level("INFO")

        # Act: run auto patch
        iframe_patch.auto_patch_browser_use()

        # After autopatch, __init__ should be swapped
        Patched = fake_session_mod.BrowserSession.__init__
        assert Patched is not Original, "BrowserSession.__init__ should have been replaced by auto_patch_browser_use."

        # Instantiate to trigger enhanced init (should call original init + enable_iframe_support)
        inst = fake_session_mod.BrowserSession(1, key="v")

        # Assert: original init side effects and enable_iframe_support called with instance
        assert getattr(inst, "inited", False) is True, "Original __init__ side effects should still occur."
        assert calls and calls[0] is inst, "enable_iframe_support must be invoked with the BrowserSession instance."

        # Also verify logging of success path (optional info log)
        assert any("auto-patched" in rec.message.lower() for rec in caplog.records), \
            "Expected log indicating auto patch completed."


def test_auto_patch_browser_use_logs_on_import_failure(caplog):
    # Arrange: Ensure iframe_detection exists so importing iframe_patch succeeds,
    # but force browser_use.browser.session import to fail inside auto_patch_browser_use.
    make_fake_browser_use_modules()
    # Remove the session module to trigger ModuleNotFoundError during auto_patch
    sys.modules.pop("browser_use.browser.session", None)

    with isolated_import("iframe_patch") as iframe_patch:
        caplog.clear()
        caplog.set_level("ERROR")

        # Act
        iframe_patch.auto_patch_browser_use()

        # Assert
        assert any("Auto-patch failed" in rec.message for rec in caplog.records), \
            "Expected ERROR log when auto-patch import fails."


def test_enable_iframe_support_propagates_return_value_types(monkeypatch):
    # Arrange different return types from patch function and verify passthrough
    for retval in (42, "done", ["a", "b"], {"x": 1}, None):
        make_fake_browser_use_modules(patch_func_behavior="return", return_value=retval)
        with isolated_import("iframe_patch") as iframe_patch:
            got = iframe_patch.enable_iframe_support(object())
            assert got == retval, f"enable_iframe_support should return the exact value from patch function: {retval!r}"

# ---------------------------------------------------------------------------
# Additional tests (Framework: pytest)
# These tests extend coverage for error paths, idempotency, and edge cases.
# ---------------------------------------------------------------------------

def test_enable_iframe_support_missing_iframe_detection_module(caplog):
    # Arrange: create fakes, then remove iframe_detection to force ImportError path
    make_fake_browser_use_modules()
    sys.modules.pop("browser_use.iframe_detection", None)

    with isolated_import("iframe_patch") as iframe_patch:
        caplog.clear()
        caplog.set_level("ERROR")

        # Act
        result = iframe_patch.enable_iframe_support(object())

        # Assert
        assert result is None
        assert any("Failed to enable iframe support" in rec.message for rec in caplog.records), \
            "Expected ERROR log when iframe_detection module is missing."


def test_enable_iframe_support_missing_patch_function_logs_error_and_returns_none(caplog):
    # Arrange: create fakes but remove the expected patch function attribute
    fake_iframe_mod, _ = make_fake_browser_use_modules()
    if hasattr(fake_iframe_mod, "patch_browser_use_with_iframe_support"):
        delattr(fake_iframe_mod, "patch_browser_use_with_iframe_support")

    with isolated_import("iframe_patch") as iframe_patch:
        caplog.clear()
        caplog.set_level("ERROR")

        # Act
        result = iframe_patch.enable_iframe_support(object())

        # Assert
        assert result is None, "Should return None when patch function is unavailable."
        # Be tolerant to message wording but require a clear failure signal
        assert any("Failed to enable iframe support" in rec.message or
                   "patch_browser_use_with_iframe_support" in rec.message
                   for rec in caplog.records), \
            "Expected ERROR log indicating missing patch function."


def test_auto_patch_browser_use_is_idempotent(monkeypatch):
    # Arrange
    _, fake_session_mod = make_fake_browser_use_modules()
    with isolated_import("iframe_patch") as iframe_patch:
        calls = []

        def fake_enable(self):
            calls.append(self)

        monkeypatch.setattr(iframe_patch, "enable_iframe_support", fake_enable, raising=True)

        # Act: first patch
        iframe_patch.auto_patch_browser_use()
        first = fake_session_mod.BrowserSession.__init__

        # Act: second patch should NOT wrap again
        iframe_patch.auto_patch_browser_use()
        second = fake_session_mod.BrowserSession.__init__

        # Assert: same function object -> not double-wrapped
        assert first is second, "auto_patch_browser_use should be idempotent and avoid double-wrapping __init__."

        # Instantiate a couple of times to ensure wrapper still functional
        inst1 = fake_session_mod.BrowserSession()
        inst2 = fake_session_mod.BrowserSession()
        assert len(calls) == 2 and calls[0] is inst1 and calls[1] is inst2, \
            "Patched __init__ must call enable_iframe_support exactly once per instantiation."


def test_auto_patch_browser_use_handles_class_without_custom_init(monkeypatch):
    # Arrange: simulate BrowserSession without a custom __init__
    _, fake_session_mod = make_fake_browser_use_modules()
    fake_session_mod.BrowserSession.__init__ = object.__init__  # no custom side-effects

    with isolated_import("iframe_patch") as iframe_patch:
        calls = []

        def fake_enable(self):
            calls.append(self)

        monkeypatch.setattr(iframe_patch, "enable_iframe_support", fake_enable, raising=True)

        # Act: autopatch and instantiate with no args (object.__init__ accepts only self)
        iframe_patch.auto_patch_browser_use()
        inst = fake_session_mod.BrowserSession()

        # Assert: enable_iframe_support still invoked with the created instance
        assert calls and calls[0] is inst, \
            "enable_iframe_support should be invoked even when BrowserSession has no custom __init__."


def test_auto_patch_browser_use_continues_when_enable_raises(monkeypatch, caplog):
    # Arrange
    _, fake_session_mod = make_fake_browser_use_modules()
    with isolated_import("iframe_patch") as iframe_patch:
        def raising_enable(self):
            raise RuntimeError("enable failed")

        monkeypatch.setattr(iframe_patch, "enable_iframe_support", raising_enable, raising=True)

        caplog.clear()
        caplog.set_level("ERROR")

        # Act: autopatch and construct session
        iframe_patch.auto_patch_browser_use()
        # Should not raise during construction; original __init__ should still run
        inst = fake_session_mod.BrowserSession(11, key="v")

        # Assert: original init side effects preserved and error logged
        assert getattr(inst, "inited", False) is True, "Original __init__ side effects must still occur."
        assert any(("enable" in rec.message.lower() and "fail" in rec.message.lower()) or
                   "Failed to enable iframe support" in rec.message
                   for rec in caplog.records), \
            "Expected an ERROR log when enable_iframe_support raises within patched __init__."
