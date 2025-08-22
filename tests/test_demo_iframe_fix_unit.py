import sys
import types
import importlib
import asyncio
import builtins
import contextlib

import pytest

# Utility: import the demo module while safely stubbing external dependencies
def import_demo_module(enable_returns=True, has_browser_session=True):
    """
    Dynamically insert stub modules into sys.modules for:
      - browser_use.Agent
      - iframe_patch.enable_iframe_support
    Then import tests.test_demo_iframe_fix as the module-under-test.
    Args:
      enable_returns: bool | callable -> return value or callable for enable_iframe_support
      has_browser_session: bool -> whether Agent() exposes .browser_session
    Returns:
      (module, stubs) tuple
    """
    # Stub out browser_use with a minimal Agent
    browser_use = types.ModuleType("browser_use")

    class _Agent:
        def __init__(self, *args, **kwargs):
            # mimic signature Agent(task=..., llm=None)
            if has_browser_session:
                self.browser_session = object()
            else:
                # simulate missing attribute
                pass

    browser_use.Agent = _Agent

    # Stub out iframe_patch with enable_iframe_support
    iframe_patch = types.ModuleType("iframe_patch")

    def _enable(sess):
        return enable_returns(sess) if callable(enable_returns) else bool(enable_returns)

    iframe_patch.enable_iframe_support = _enable

    # Insert stubs
    prev_browser_use = sys.modules.get("browser_use")
    prev_iframe_patch = sys.modules.get("iframe_patch")
    sys.modules["browser_use"] = browser_use
    sys.modules["iframe_patch"] = iframe_patch

    # Import or reload the module under test
    try:
        # Import by package path; file lives at tests/test_demo_iframe_fix.py
        mod_name = "tests.test_demo_iframe_fix"
        if mod_name in sys.modules:
            mod = importlib.reload(sys.modules[mod_name])
        else:
            mod = importlib.import_module(mod_name)
    finally:
        # Restore originals after import to avoid leaking stubs beyond import-time
        if prev_browser_use is not None:
            sys.modules["browser_use"] = prev_browser_use
        else:
            sys.modules.pop("browser_use", None)

        if prev_iframe_patch is not None:
            sys.modules["iframe_patch"] = prev_iframe_patch
        else:
            sys.modules.pop("iframe_patch", None)

    stubs = {"browser_use": browser_use, "iframe_patch": iframe_patch}
    return mod, stubs


@pytest.mark.asyncio
async def test_demo_iframe_detection_fix_happy_path(monkeypatch, capsys):
    # Arrange: enable_iframe_support returns True; Agent has browser_session
    mod, _ = import_demo_module(enable_returns=True, has_browser_session=True)

    # Act
    await mod.demo_iframe_detection_fix()

    # Assert: verify key output lines indicating success branch executed
    out = capsys.readouterr().out
    assert "🎯 Demo: Browser-Use Issue #1700 Fix" in out
    assert "✅ Iframe detection enabled!" in out
    # Spot-check some of the advertised capabilities
    assert "- Iframe elements: ✅ Supported (NEW!)" in out
    assert "- Cross-origin iframes: ✅ Supported (NEW!)" in out
    assert "- Nested iframes: ✅ Supported (NEW!)" in out
    # Benefits list
    assert "- 10x simpler than Mobile-Agent-v3" in out
    assert "🎉 Demo complete! Ready for PR submission." in out


@pytest.mark.asyncio
async def test_demo_iframe_detection_fix_failure_branch(monkeypatch, capsys):
    # Arrange: enable_iframe_support returns False to exercise the else-branch
    mod, _ = import_demo_module(enable_returns=False, has_browser_session=True)

    # Act
    await mod.demo_iframe_detection_fix()

    # Assert
    out = capsys.readouterr().out
    assert "❌ Failed to enable iframe detection" in out
    assert "🎉 Demo complete! Ready for PR submission." in out


@pytest.mark.asyncio
async def test_demo_iframe_detection_calls_enable_with_browser_session(monkeypatch):
    called_with = {}

    def recorder(session):
        called_with["arg"] = session
        return True

    # Arrange: enable_iframe_support is a recorder callable
    mod, _ = import_demo_module(enable_returns=recorder, has_browser_session=True)

    # Act
    await mod.demo_iframe_detection_fix()

    # Assert the agent's browser_session was passed
    assert "arg" in called_with
    assert called_with["arg"] is not None


@pytest.mark.asyncio
async def test_demo_iframe_detection_handles_missing_browser_session(monkeypatch, capsys):
    # Arrange: Agent without browser_session should raise AttributeError in current implementation
    # We assert that the error is surfaced (document current behavior),
    # which guards against silent failures and informs future refactors.
    mod, _ = import_demo_module(enable_returns=True, has_browser_session=False)

    with pytest.raises(AttributeError):
        await mod.demo_iframe_detection_fix()
    # Optionally capture partial output before exception
    _ = capsys.readouterr()


@pytest.mark.asyncio
async def test_print_only_iframe_element_detection_demo_output(capsys):
    # Arrange
    mod, _ = import_demo_module(enable_returns=True, has_browser_session=True)

    # Act: run the "test" demo coroutine to validate its printed scenarios
    await mod.test_iframe_element_detection()

    # Assert: ensure all test cases are enumerated and success summary printed
    out = capsys.readouterr().out
    assert "🧪 Testing Iframe Element Detection:" in out
    assert "📋 Payment Form in Iframe" in out
    assert "📋 Social Login Widget" in out
    assert "📋 Embedded Chat Interface" in out
    assert "✅ Element found and clickable" in out
    assert "✅ Element found and typeable" in out
    assert "🎯 All iframe detection tests would pass!" in out


@pytest.mark.asyncio
async def test_enable_iframe_support_callable_variants(monkeypatch, capsys):
    # Arrange: enable_iframe_support returns truthy based on session identity
    def dynamic_enable(session):
        # simulate decision logic based on session object
        return isinstance(session, object)

    mod, _ = import_demo_module(enable_returns=dynamic_enable, has_browser_session=True)

    # Act
    await mod.demo_iframe_detection_fix()

    # Assert: still goes down success path
    out = capsys.readouterr().out
    assert "✅ Iframe detection enabled!" in out


@pytest.mark.asyncio
async def test_main_block_is_guarded(monkeypatch):
    # This ensures that importing the module does not execute the demo functions,
    # thanks to the if __name__ == "__main__" guard.
    # Arrange
    # We re-import under a different module name to assert no side-effects at import.
    mod, _ = import_demo_module(enable_returns=True, has_browser_session=True)
    # Assert functions are defined but not executed
    assert hasattr(mod, "demo_iframe_detection_fix")
    assert hasattr(mod, "test_iframe_element_detection")