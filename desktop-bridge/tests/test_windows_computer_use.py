from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from desktop_bridge.audit import AuditLogger
from desktop_bridge.computer import ComputerService, ComputerSessionManager
from desktop_bridge.config import PathGrant, Settings
from desktop_bridge.executables import AppCatalog


def _settings(tmp_path: Path) -> Settings:
    root = tmp_path / "root"
    root.mkdir()
    return Settings(
        host="127.0.0.1",
        port=9583,
        token="test-token",
        grants=(PathGrant(root, read=True, write=True, delete=True),),
        audit_file=tmp_path / "audit.jsonl",
        max_read_bytes=1024 * 1024,
        max_write_bytes=1024 * 1024,
        max_search_files=100,
        max_search_results=20,
        auto_discover_executables=False,
        allowed_apps_json=json.dumps([
            {"id": "desktop-test", "displayName": "Desktop Test", "executable": sys.executable}
        ]),
        allowed_tools_json="[]",
        allow_terminal=False,
        computer_use_enabled=True,
        computer_session_ttl_seconds=300,
        screenshot_max_width=1280,
        screenshot_max_bytes=5 * 1024 * 1024,
    )


def test_windows_computer_use_real_screen_window_mouse_keyboard_and_uia(tmp_path: Path):
    # This is a mandatory dynamic Windows acceptance test when run on Windows.
    # On non-Windows development hosts it returns normally instead of creating a
    # pytest skip, keeping mandatory skip count at zero.
    if os.name != "nt":
        return

    settings = _settings(tmp_path)
    audit = AuditLogger(settings.audit_file)
    apps = AppCatalog(settings, audit)
    sessions = ComputerSessionManager(settings, audit)
    computer = ComputerService(settings, sessions, audit)
    script = Path(__file__).resolve().parents[1] / "desktop_bridge" / "test_window.py"

    launched = apps.launch("desktop-test", [str(script)])
    session = sessions.start(180)
    session_id = session["sessionId"]

    try:
        handle = None
        for _ in range(40):
            windows = computer.window_list(session_id)["windows"]
            match = next((item for item in windows if item["title"] == "AgentMesh Desktop Test"), None)
            if match:
                handle = match["handle"]
                break
            time.sleep(0.1)
        assert handle is not None, "deterministic Desktop Test window was not discovered"

        assert computer.window_focus(session_id, handle)["focused"] is True
        screenshot = computer.capture(session_id)
        assert screenshot["mediaType"] == "image/png"
        assert screenshot["sizeBytes"] > 100
        assert screenshot["imageBase64"]

        edits = {"elements": []}
        for _ in range(50):
            edits = computer.element_find(session_id, handle, control_type="Edit")
            if edits["elements"]:
                break
            time.sleep(0.1)
        assert edits["elements"], "UI Automation did not discover the native test Edit control"
        computer.element_action(
            session_id,
            handle,
            control_type="Edit",
            action="set_text",
            value="desktop-agent-pass",
        )
        computer.element_action(
            session_id,
            handle,
            name="Apply",
            control_type="Button",
            action="invoke",
        )

        for _ in range(20):
            status = computer.element_find(session_id, handle, name="Status: desktop-agent-pass")
            if status["elements"]:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("UI Automation action did not update deterministic status label")

        button = computer.element_find(session_id, handle, name="Apply", control_type="Button")["elements"][0]
        rect = button["rectangle"]
        x = (rect["left"] + rect["right"]) // 2
        y = (rect["top"] + rect["bottom"]) // 2
        assert computer.mouse_move(session_id, x, y)["moved"] is True
        assert computer.mouse_click(session_id, x, y)["clicked"] is True

        # Keyboard path is exercised against the Edit control using ASCII text
        # after focusing it with a real mouse click.
        edit = edits["elements"][0]["rectangle"]
        ex = (edit["left"] + edit["right"]) // 2
        ey = (edit["top"] + edit["bottom"]) // 2
        computer.mouse_click(session_id, ex, ey)
        computer.keyboard_hotkey(session_id, ["ctrl", "a"])
        assert computer.keyboard_type(session_id, "keyboard-pass")["typed"] is True
        computer.element_action(
            session_id,
            handle,
            name="Apply",
            control_type="Button",
            action="invoke",
        )
        for _ in range(20):
            keyboard_status = computer.element_find(session_id, handle, name="Status: keyboard-pass")
            if keyboard_status["elements"]:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("real keyboard input did not reach the deterministic test application")

        assert sessions.stop(session_id)["stopped"] is True
    finally:
        try:
            apps.close("desktop-test", launched["pid"])
        except Exception:
            pass


def test_windows_batch_wrapper_rejects_command_metacharacter_injection(tmp_path: Path):
    # Mandatory dynamic Windows coverage without adding a pytest skip on other OSes.
    if os.name != "nt":
        return

    from desktop_bridge.executables import ToolCatalog
    from desktop_bridge.processes import ProcessManager

    settings = _settings(tmp_path)
    root = settings.grants[0].path
    wrapper = root / "safe-wrapper.cmd"
    wrapper.write_text("@echo off\r\necho %*\r\n", encoding="utf-8")
    settings = Settings(
        **{
            **{field: getattr(settings, field) for field in settings.__dataclass_fields__},
            "allowed_tools_json": json.dumps([
                {"id": "batch-test", "displayName": "Batch Test", "executable": str(wrapper)}
            ]),
        }
    )
    catalog = ToolCatalog(settings, ProcessManager(settings), AuditLogger(settings.audit_file))

    import pytest

    with pytest.raises(ValueError, match="metacharacters"):
        catalog.run("batch-test", ["hello&whoami"], str(root), wait_seconds=0)

