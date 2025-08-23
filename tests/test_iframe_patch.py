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


@contextlib.contextmanager
def fake_browser_use_modules(patch_func_behavior="return", return_value="IFRAME-OK", raise_exc=None):
    """
    Context manager that creates and registers fake 'browser_use' package structure in sys.modules:
      - browser_use (package)
      - browser_use.iframe_detection (module) with patch_browser_use_with_iframe_support
      - browser_use.browser (package)
      - browser_use.browser.session (module) with BrowserSession
    The behavior of 'patch_browser_use_with_iframe_support' can be:
      - "return": returns return_value
      - "raise": raises raise_exc
    """
    # Store original modules to restore later
    original_modules = {}
    module_names = ["browser_use", "browser_use.iframe_detection", "browser_use.browser", "browser_use.browser.session"]
    
    for name in module_names:
        if name in sys.modules:
            original_modules[name] = sys.modules[name]
        else:
            original_modules[name] = None

    try:
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

        yield iframe_detection, session_mod
    finally:
        # Restore original modules
        for name in module_names:
            if original_modules[name] is not None:
                sys.modules[name] = original_modules[name]
            else:
                sys.modules.pop(name, None)


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
    with fake_browser_use_modules(patch_func_behavior="return", return_value={"status": "ok", "patched": True}) as (fake_iframe_mod, _):
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
    with fake_browser_use_modules(patch_func_behavior="raise", raise_exc=ValueError("bad session")):
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
    with fake_browser_use_modules() as (_, fake_session_mod):
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
    with fake_browser_use_modules():
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
        with fake_browser_use_modules(patch_func_behavior="return", return_value=retval):
            with isolated_import("iframe_patch") as iframe_patch:
                got = iframe_patch.enable_iframe_support(object())
                assert got == retval, f"enable_iframe_support should return the exact value from patch function: {retval!r}"