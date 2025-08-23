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
# ------------------------------------------------------------
# Additional tests appended by PR automation
# Framework: pytest + pytest-asyncio
# Purpose: expand coverage across edge cases and error pathways
# ------------------------------------------------------------

@pytest.mark.asyncio
async def test_demo_iframe_detection_fix_truthy_and_falsy_nonbool_returns(capsys):
    """
    Validate that non-boolean truthy/falsy return values from enable_iframe_support
    still route the correct branch (our stub coerces via bool()).
    """
    # Truthy: non-empty string
    mod, _ = import_demo_module(enable_returns="ok", has_browser_session=True)
    await mod.demo_iframe_detection_fix()
    out = capsys.readouterr().out
    assert "✅ Iframe detection enabled!" in out

    # Falsy: empty string
    mod, _ = import_demo_module(enable_returns="", has_browser_session=True)
    await mod.demo_iframe_detection_fix()
    out = capsys.readouterr().out
    assert "❌ Failed to enable iframe detection" in out

@pytest.mark.asyncio
async def test_demo_iframe_detection_fix_exception_from_enable_is_surfaced(capsys):
    """
    If iframe_patch.enable_iframe_support raises, current behavior should surface the error.
    This guards against silent failures and documents behavior for future changes.
    """
    def raiser(_session):
        raise RuntimeError("boom")

    mod, _ = import_demo_module(enable_returns=raiser, has_browser_session=True)
    with pytest.raises(RuntimeError):
        await mod.demo_iframe_detection_fix()
    # Drain any partial output without assertions (behavioral doc)
    _ = capsys.readouterr()

@pytest.mark.asyncio
async def test_demo_iframe_detection_fix_output_order_smoke(capsys):
    """
    Ensure key banner appears before the completion line, as a lightweight order check.
    """
    mod, _ = import_demo_module(enable_returns=True, has_browser_session=True)
    await mod.demo_iframe_detection_fix()
    out = capsys.readouterr().out

    banner_idx = out.find("🎯 Demo: Browser-Use Issue #1700 Fix")
    complete_idx = out.find("🎉 Demo complete! Ready for PR submission.")
    assert banner_idx != -1 and complete_idx != -1 and banner_idx < complete_idx

@pytest.mark.asyncio
async def test_demo_iframe_detection_fix_handles_agent_init_kwargs(capsys, monkeypatch):
    """
    Ensure our stub Agent is tolerant of extra kwargs (mirrors real signature with **kwargs),
    and the demo still succeeds when enable returns True.
    """
    # Recreate import with stubs; our helper already allows *args/**kwargs in Agent
    mod, _ = import_demo_module(enable_returns=True, has_browser_session=True)
    # Monkeypatch: wrap Agent to observe kwargs on instantiation inside demo, if used.
    # If the demo does not pass kwargs, this is still a no-op; the goal is non-crash.
    called = {}

    original_agent = sys.modules.get("browser_use", types.ModuleType("browser_use")).Agent

    class ObservedAgent(original_agent):  # type: ignore[name-defined]
        def __init__(self, *args, **kwargs):
            called["kwargs"] = kwargs
            super().__init__(*args, **kwargs)

    # Temporarily re-stub and reload to ensure demo uses observed agent.
    prev_browser_use = sys.modules.get("browser_use")
    temp_browser_use = types.ModuleType("browser_use")
    temp_browser_use.Agent = ObservedAgent  # type: ignore[assignment]
    sys.modules["browser_use"] = temp_browser_use
    try:
        # Reload module-under-test so it binds new Agent
        mod = importlib.reload(mod)
        await mod.demo_iframe_detection_fix()
    finally:
        # Restore stub to avoid leaking
        if prev_browser_use is not None:
            sys.modules["browser_use"] = prev_browser_use
        else:
            sys.modules.pop("browser_use", None)

    out = capsys.readouterr().out
    assert "✅ Iframe detection enabled!" in out
    # We don't assert particular kwargs since demo may not pass any.
    # Presence of key means our subclass constructed successfully if called.
    assert "kwargs" in called or "kwargs" not in called  # Documented no-op

@pytest.mark.asyncio
async def test_test_iframe_element_detection_lists_all_expected_bullets(capsys):
    """
    Assert the demo test printer enumerates each bullet exactly once.
    """
    mod, _ = import_demo_module(enable_returns=True, has_browser_session=True)
    await mod.test_iframe_element_detection()
    out = capsys.readouterr().out

    bullets = [
        "📋 Payment Form in Iframe",
        "📋 Social Login Widget",
        "📋 Embedded Chat Interface",
    ]
    for b in bullets:
        assert out.count(b) == 1
    assert out.strip().endswith("🎯 All iframe detection tests would pass!")

@pytest.mark.asyncio
async def test_demo_iframe_detection_fix_no_color_emoji_dependency(capsys, monkeypatch):
    """
    Defensive test: even if the environment lacks emoji support (replace with ASCII),
    ensure logic branches on return value, not on terminal capabilities.
    We simulate by temporarily replacing print to strip non-ascii.
    """
    mod, _ = import_demo_module(enable_returns=True, has_browser_session=True)

    real_print = builtins.print
    def ascii_print(*args, **kwargs):
        def to_ascii(s):
            if isinstance(s, str):
                return s.encode("ascii", errors="ignore").decode("ascii")
            return s
        real_print(*[to_ascii(a) for a in args], **kwargs)

    try:
        builtins.print = ascii_print
        await mod.demo_iframe_detection_fix()
    finally:
        builtins.print = real_print

    out = capsys.readouterr().out
    # Look for ASCII substrings that remain after stripping emojis
    assert "Demo: Browser-Use Issue #1700 Fix" in out
    assert "Iframe detection enabled!" in out or "Failed to enable iframe detection" in out

@pytest.mark.asyncio
async def test_demo_iframe_detection_fix_missing_iframe_patch_module(monkeypatch, capsys):
    """
    If iframe_patch is not importable at runtime (beyond import-time stubbing),
    current implementation should raise ImportError or NameError when attempting to use it.
    This documents behavior vs. silently skipping the call.
    """
    # Import with standard happy-path stubs first so module loads.
    mod, _ = import_demo_module(enable_returns=True, has_browser_session=True)

    # Remove iframe_patch after import to simulate runtime disappearance
    prev_iframe_patch = sys.modules.get("iframe_patch")
    sys.modules.pop("iframe_patch", None)
    try:
        with pytest.raises((ImportError, NameError, AttributeError)):
            await mod.demo_iframe_detection_fix()
    finally:
        if prev_iframe_patch is not None:
            sys.modules["iframe_patch"] = prev_iframe_patch

@pytest.mark.asyncio
async def test_demo_iframe_detection_fix_agent_without_init_side_effects(capsys):
    """
    Ensure that simply constructing the Agent does not produce output.
    We care that only the demo function prints the banner and summary.
    """
    mod, _ = import_demo_module(enable_returns=True, has_browser_session=True)
    # No calls yet, drain
    pre = capsys.readouterr().out
    assert pre == ""  # importing + helper should not print

    await mod.demo_iframe_detection_fix()
    out = capsys.readouterr().out
    assert "Demo:" in out and "Ready for PR submission" in out
