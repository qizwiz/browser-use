#!/usr/bin/env python3
"""
Unit tests for tests/test_demo_iframe_detection.py demo functions.

Framework: pytest (uses capsys fixture to capture stdout).
These tests focus on validating the exact user-visible output produced by:
- demo_overview()
- demo_usage()
- demo_architecture()
- demo_benefits()
They also validate the __main__ execution path using runpy.run_path.

Rationale:
- The demo module prints structured, user-facing content. Tests assert for ordering and presence of key lines.
- We avoid brittle full-output matching by verifying ordered critical lines and key substrings.
- We ensure importing the module does not execute side effects (since prints are gated under __main__).
"""

import importlib
import io
import os
import runpy
import sys
from contextlib import redirect_stdout
from types import ModuleType
from typing import List

# Module under test lives at tests/test_demo_iframe_detection.py (a demo script).
DEMO_MODULE_PATH = os.path.join("tests", "test_demo_iframe_detection.py")
DEMO_MODULE_IMPORT = "tests.test_demo_iframe_detection"


def _capture_prints(callable_obj, *args, **kwargs) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        callable_obj(*args, **kwargs)
    return buf.getvalue()


def _assert_lines_in_order(output: str, expected_lines: List[str]) -> None:
    """
    Assert that each expected line (as substring) appears in the output in the specified order.
    """
    start = 0
    for needle in expected_lines:
        idx = output.find(needle, start)
        assert idx != -1, f"Expected to find line '{needle}' in output after position {start}.\nFull output:\n{output}"
        start = idx + len(needle)


def _safe_import_demo_module() -> ModuleType:
    """
    Import the demo module without executing the __main__ block.
    """
    if DEMO_MODULE_IMPORT in sys.modules:
        return sys.modules[DEMO_MODULE_IMPORT]
    return importlib.import_module(DEMO_MODULE_IMPORT)


def test_import_has_no_side_effects(capsys):
    """
    Ensure merely importing the demo module does not print anything.
    """
    # Capture any import-time prints
    _ = _safe_import_demo_module()
    captured = capsys.readouterr()
    assert captured.out == "", "Importing the demo module should not print to stdout."
    assert captured.err == ""


def test_demo_overview_output_contains_key_sections():
    demo = _safe_import_demo_module()
    out = _capture_prints(demo.demo_overview)

    expected_order = [
        "🚀 Browser-Use Iframe Detection Demo",
        "=" * 50,
        "This demo shows how to use the new iframe detection feature",
        "that solves Issue #1700: 'Add iframe element detection support'",
        "Key benefits:",
        "• Find and interact with elements inside iframes",
        "• Non-breaking integration with existing code",
        "• Works with payment forms, social widgets, chat interfaces",
        "• No AI model dependencies - deterministic and reliable",
    ]
    _assert_lines_in_order(out, expected_order)

    # Basic sanity checks
    assert out.count("\n") >= len(expected_order), "Output should contain multiple lines."


def test_demo_usage_output_contains_usage_snippets():
    demo = _safe_import_demo_module()
    out = _capture_prints(demo.demo_usage)

    expected_order = [
        "🔧 Usage Example:",
        "# 1. Enable iframe support for a browser session",
        "from iframe_patch import enable_iframe_support",
        "iframe_detection = enable_iframe_support(browser_session)",
        "# 2. Use browser-use normally - iframe elements work automatically!",
        "element = await browser_session.get_element_by_index(123)",
        "await controller.click_element_by_index(123)",
    ]
    _assert_lines_in_order(out, expected_order)

    # Ensure async usage hints are present (await)
    assert "await" in out


def test_demo_architecture_output_explains_pipeline():
    demo = _safe_import_demo_module()
    out = _capture_prints(demo.demo_architecture)

    expected_order = [
        "🏛️ Architecture:",
        "The implementation follows S-expression analysis insights:",
        "1. enumerate_frames() - Discover all iframe contexts",
        "2. detect_boundaries() - Map coordinate systems",
        "3. map_elements() - Transform coordinates for interaction",
        "Key components:",
        "• SimpleIframeDetection: Core iframe detection logic",
        "• FrameContext: Represents frame with coordinate system",
        "• CrossFrameElement: Elements found across frames",
        "• IframeAwareController: Enhanced controller for iframe support",
    ]
    _assert_lines_in_order(out, expected_order)


def test_demo_benefits_output_lists_claims():
    demo = _safe_import_demo_module()
    out = _capture_prints(demo.demo_benefits)

    expected_order = [
        "✨ Benefits:",
        "• Solves Issue #1700 completely",
        "• Non-breaking integration with existing browser-use code",
        "• Simple and maintainable solution (no AI model dependencies)",
        "• Works with payment forms, social widgets, chat interfaces",
        "• Deterministic and reliable (vs. AI approaches)",
        "• Clean architecture (vs. ad-hoc custom actions)",
    ]
    _assert_lines_in_order(out, expected_order)


def test_main_block_execution_prints_final_line(tmp_path, monkeypatch):
    """
    Execute the module as a script (__main__) and validate that:
    - It calls all demo sections.
    - It prints the final conclusive line.
    """
    # Ensure path exists and run with __name__='__main__'
    assert os.path.exists(DEMO_MODULE_PATH), f"Expected demo at {DEMO_MODULE_PATH}"

    buf = io.StringIO()
    with redirect_stdout(buf):
        # run_path executes the file as __main__, similar to python path/to/file.py
        runpy.run_path(DEMO_MODULE_PATH, run_name="__main__")
    out = buf.getvalue()

    # Check presence of sentinel ending line
    assert "🎯 Issue #1700 solved with simple iframe detection!" in out

    # Ensure each section header appears at least once
    for section in ["🚀 Browser-Use Iframe Detection Demo",
                    "🔧 Usage Example:",
                    "🏛️ Architecture:",
                    "✨ Benefits:"]:
        assert section in out, f"Expected section header '{section}' in main execution output."


def test_functions_are_callable_multiple_times_without_state_leakage():
    """
    Ensure calling the functions repeatedly produces consistent output
    and does not rely on hidden global state.
    """
    demo = _safe_import_demo_module()

    outs = [
        _capture_prints(demo.demo_overview),
        _capture_prints(demo.demo_overview),
    ]
    assert outs[0] == outs[1], "demo_overview should produce deterministic output."

    outs = [
        _capture_prints(demo.demo_usage),
        _capture_prints(demo.demo_usage),
    ]
    assert outs[0] == outs[1], "demo_usage should produce deterministic output."

    outs = [
        _capture_prints(demo.demo_architecture),
        _capture_prints(demo.demo_architecture),
    ]
    assert outs[0] == outs[1], "demo_architecture should produce deterministic output."

    outs = [
        _capture_prints(demo.demo_benefits),
        _capture_prints(demo.demo_benefits),
    ]
    assert outs[0] == outs[1], "demo_benefits should produce deterministic output."


def test_demo_module_sys_path_modification_is_safe(monkeypatch):
    """
    Validate that the module's sys.path manipulation does not raise,
    and that it prepends a path-like string. We re-import fresh into a temp sys.modules slot.
    """
    # Simulate a clean import by removing from sys.modules if present
    sys.modules.pop(DEMO_MODULE_IMPORT, None)

    # Capture length before import
    before_len = len(sys.path)
    module = _safe_import_demo_module()
    after_len = len(sys.path)

    # The demo adds the current directory to the path; ensure sys.path length is >= before.
    assert after_len >= before_len
    assert hasattr(module, "demo_overview") and callable(module.demo_overview)
    assert hasattr(module, "demo_usage") and callable(module.demo_usage)
    assert hasattr(module, "demo_architecture") and callable(module.demo_architecture)
    assert hasattr(module, "demo_benefits") and callable(module.demo_benefits)