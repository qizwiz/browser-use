import io
import sys
from pathlib import Path
import importlib.util
import types
import textwrap

DEMO_PATH = Path(__file__).parent / "test_demo_iframe_detection.py"

def _load_demo_module():
    """
    Load the demo module from its path without requiring 'tests' to be a package.
    Returns the loaded module object.
    """
    spec = importlib.util.spec_from_file_location("demo_iframe_detection", DEMO_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None, "Could not load spec for demo module"
    spec.loader.exec_module(module)
    return module

def _normalize(s: str) -> str:
    # Normalize newlines and strip trailing spaces for robust comparisons
    return "\n".join(line.rstrip() for line in s.replace("\r\n", "\n").replace("\r", "\n").split("\n"))

def test_demo_overview_prints_expected_intro(capsys):
    demo = _load_demo_module()
    demo.demo_overview()
    captured = capsys.readouterr().out
    out = _normalize(captured)
    # Core header and section markers
    assert "🚀 Browser-Use Iframe Detection Demo" in out
    assert "=" * 50 in out
    # Key narrative lines
    assert "This demo shows how to use the new iframe detection feature" in out
    assert "that solves Issue #1700: 'Add iframe element detection support'" in out
    # Bulleted key benefits overview
    assert "Key benefits:" in out
    for bullet in [
        "Find and interact with elements inside iframes",
        "Non-breaking integration with existing code",
        "Works with payment forms, social widgets, chat interfaces",
        "No AI model dependencies - deterministic and reliable",
    ]:
        assert bullet in out

def test_demo_usage_prints_step_by_step_instructions(capsys):
    demo = _load_demo_module()
    demo.demo_usage()
    out = _normalize(capsys.readouterr().out)
    assert "🔧 Usage Example:" in out
    # Step 1: enabling iframe support
    assert "Enable iframe support for a browser session" in out
    assert "from iframe_patch import enable_iframe_support" in out
    assert "iframe_detection = enable_iframe_support(browser_session)" in out
    # Step 2: automatic integration mentions
    assert "Use browser-use normally - iframe elements work automatically!" in out
    # Example API usage lines
    assert "element = await browser_session.get_element_by_index(123)  # Works in iframes!" in out
    assert "await controller.click_element_by_index(123)  # Clicks iframe elements!" in out

def test_demo_architecture_describes_components_and_pipeline(capsys):
    demo = _load_demo_module()
    demo.demo_architecture()
    out = _normalize(capsys.readouterr().out)
    assert "🏛️ Architecture:" in out
    # Pipeline steps
    assert "enumerate_frames() - Discover all iframe contexts" in out
    assert "detect_boundaries() - Map coordinate systems" in out
    assert "map_elements() - Transform coordinates for interaction" in out
    # Components list
    for component in [
        "SimpleIframeDetection: Core iframe detection logic",
        "FrameContext: Represents frame with coordinate system",
        "CrossFrameElement: Elements found across frames",
        "IframeAwareController: Enhanced controller for iframe support",
    ]:
        assert component in out

def test_demo_benefits_lists_unique_value_props(capsys):
    demo = _load_demo_module()
    demo.demo_benefits()
    out = _normalize(capsys.readouterr().out)
    assert "✨ Benefits:" in out
    expected_benefits = [
        "Solves Issue #1700 completely",
        "Non-breaking integration with existing browser-use code",
        "Simple and maintainable solution (no AI model dependencies)",
        "Works with payment forms, social widgets, chat interfaces",
        "Deterministic and reliable (vs. AI approaches)",
        "Clean architecture (vs. ad-hoc custom actions)",
    ]
    for b in expected_benefits:
        assert b in out

def test_main_guard_runs_all_demos_and_final_message(capsys, monkeypatch):
    """
    Simulate running the module as a script: __name__ == '__main__'
    We execute the file with runpy to trigger the main block and assert the full narrative appears in order.
    """
    import runpy
    # Ensure a clean stdout capture
    runpy.run_path(str(DEMO_PATH), run_name="__main__")
    out = _normalize(capsys.readouterr().out)

    # Check that each section header appears
    assert "🚀 Browser-Use Iframe Detection Demo" in out
    assert "🔧 Usage Example:" in out
    assert "🏛️ Architecture:" in out
    assert "✨ Benefits:" in out

    # Final confirmation line from __main__ section
    assert "🎯 Issue #1700 solved with simple iframe detection!" in out

def test_functions_do_not_raise_on_multiple_invocations(capsys):
    """
    Edge case: Call the demo functions multiple times to ensure idempotent printing
    and no state leakage across invocations.
    """
    demo = _load_demo_module()
    for fn_name in ("demo_overview", "demo_usage", "demo_architecture", "demo_benefits"):
        fn = getattr(demo, fn_name)
        fn()
        fn()  # call twice
    out = _normalize(capsys.readouterr().out)
    # Ensure duplicated key lines exist at least twice
    assert out.count("🚀 Browser-Use Iframe Detection Demo") >= 2
    assert out.count("🔧 Usage Example:") >= 2
    assert out.count("🏛️ Architecture:") >= 2
    assert out.count("✨ Benefits:") >= 2

def test_module_import_is_side_effect_safe(monkeypatch):
    """
    Validate that importing the module does not print to stdout or raise.
    This ensures test collection won't produce unexpected output.
    """
    # Capture stdout manually to double-check no top-level prints occur on import
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        mod = _load_demo_module()
        assert isinstance(mod, types.ModuleType)
        # Nothing should have been printed during import
        assert buf.getvalue() == ""
    finally:
        sys.stdout = old_stdout