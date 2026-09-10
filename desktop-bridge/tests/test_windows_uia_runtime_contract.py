from __future__ import annotations

from pathlib import Path


def test_windows_uia_bootstraps_pywin32_dll_search_before_pywinauto_import():
    source = (
        Path(__file__).resolve().parents[1]
        / "desktop_bridge"
        / "computer.py"
    ).read_text(encoding="utf-8")

    helper = source.index("def _prepare_windows_uia_runtime")
    call = source.index("_prepare_windows_uia_runtime()", helper + 1)
    pywinauto_import = source.index("from pywinauto import Desktop", call)

    assert helper < call < pywinauto_import
    assert "pywin32_system32" in source
    assert "add_dll_directory" in source
    assert "_PYWIN32_DLL_DIRECTORY_HANDLES" in source


def test_pywin32_is_an_explicit_windows_dependency():
    requirements = (
        Path(__file__).resolve().parents[1]
        / "requirements.txt"
    ).read_text(encoding="utf-8")

    assert "pywin32" in requirements.lower()
    assert "platform_system" in requirements
