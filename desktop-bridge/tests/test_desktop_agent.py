from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from desktop_bridge.audit import AuditLogger
from desktop_bridge.computer import ComputerSessionManager
from desktop_bridge.config import PathGrant, Settings
from desktop_bridge.executables import AppCatalog, ToolCatalog
from desktop_bridge.policy import DesktopPermissionError
from desktop_bridge.processes import ProcessManager


def settings_for(tmp_path: Path, **overrides) -> Settings:
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    values = dict(
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
        allowed_apps_json="[]",
        allowed_tools_json=json.dumps([
            {"id": "python-test", "displayName": "Python Test", "executable": sys.executable}
        ]),
        allow_terminal=False,
        computer_use_enabled=False,
        process_output_max_bytes=64 * 1024,
        process_initial_wait_seconds=3.0,
    )
    values.update(overrides)
    return Settings(**values)


def test_registered_cli_run_is_background_pollable_and_bounded(tmp_path: Path):
    settings = settings_for(tmp_path)
    audit = AuditLogger(settings.audit_file)
    manager = ProcessManager(settings, audit)
    catalog = ToolCatalog(settings, manager, audit)
    root = settings.grants[0].path

    result = catalog.run(
        "python-test",
        ["-c", "print('desktop-agent-ok')"],
        str(root),
        wait_seconds=2.0,
    )

    assert result["running"] is False
    assert result["exitCode"] == 0
    assert "desktop-agent-ok" in result["stdout"]
    assert result["stderr"] == ""
    assert result["processId"]



def test_cli_process_cancel_stops_bridge_owned_process(tmp_path: Path):
    settings = settings_for(tmp_path)
    audit = AuditLogger(settings.audit_file)
    manager = ProcessManager(settings, audit)
    catalog = ToolCatalog(settings, manager, audit)

    started = catalog.run(
        "python-test",
        ["-c", "import time; time.sleep(30)"],
        str(settings.grants[0].path),
        wait_seconds=0,
    )
    assert started["running"] is True

    cancelled = catalog.cancel(started["processId"])
    assert cancelled["cancelled"] is True
    assert cancelled["running"] is False
    assert cancelled["exitCode"] is not None


def test_cli_process_output_is_bounded_and_marked_truncated(tmp_path: Path):
    settings = settings_for(tmp_path, process_output_max_bytes=1024, process_initial_wait_seconds=4.0)
    audit = AuditLogger(settings.audit_file)
    catalog = ToolCatalog(settings, ProcessManager(settings, audit), audit)

    result = catalog.run(
        "python-test",
        ["-c", "print('x' * 10000)"],
        str(settings.grants[0].path),
        wait_seconds=4.0,
    )
    assert result["running"] is False
    assert result["stdoutTruncated"] is True
    assert len(result["stdout"].encode("utf-8")) <= 1024

def test_cli_process_environment_filters_secret_like_variables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTMESH_TEST_SECRET_TOKEN", "SHOULD-NOT-LEAK")
    settings = settings_for(tmp_path)
    catalog = ToolCatalog(settings, ProcessManager(settings), AuditLogger(settings.audit_file))

    result = catalog.run(
        "python-test",
        ["-c", "import os; print(os.getenv('AGENTMESH_TEST_SECRET_TOKEN', 'missing'))"],
        str(settings.grants[0].path),
        wait_seconds=2.0,
    )
    assert "SHOULD-NOT-LEAK" not in result["stdout"]
    assert "missing" in result["stdout"]


def test_cli_cwd_must_be_authorized(tmp_path: Path):
    settings = settings_for(tmp_path)
    catalog = ToolCatalog(settings, ProcessManager(settings), AuditLogger(settings.audit_file))
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(DesktopPermissionError):
        catalog.run("python-test", ["-c", "print(1)"], str(outside), wait_seconds=0)



def test_process_status_can_long_poll_without_blocking_start_contract(tmp_path: Path):
    settings = settings_for(tmp_path, process_initial_wait_seconds=4.0)
    audit = AuditLogger(settings.audit_file)
    manager = ProcessManager(settings, audit)
    catalog = ToolCatalog(settings, manager, audit)
    root = settings.grants[0].path

    started = catalog.run(
        "python-test",
        ["-c", "import time; time.sleep(0.2); print('long-poll-ok')"],
        str(root),
        wait_seconds=0,
    )
    assert started["running"] is True

    finished = manager.wait(started["processId"], 4.0)
    assert finished["running"] is False
    assert finished["exitCode"] == 0
    assert "long-poll-ok" in finished["stdout"]


def test_cli_environment_filters_access_key_style_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA-DO-NOT-INHERIT")
    settings = settings_for(tmp_path)
    catalog = ToolCatalog(settings, ProcessManager(settings), AuditLogger(settings.audit_file))

    result = catalog.run(
        "python-test",
        ["-c", "import os; print(os.getenv('AWS_ACCESS_KEY_ID', 'missing'))"],
        str(settings.grants[0].path),
        wait_seconds=2.0,
    )
    assert "AKIA-DO-NOT-INHERIT" not in result["stdout"]
    assert "missing" in result["stdout"]

def test_computer_use_requires_explicit_enable_and_has_expiring_session(tmp_path: Path):
    disabled = settings_for(tmp_path)
    sessions = ComputerSessionManager(disabled)
    with pytest.raises(DesktopPermissionError):
        sessions.start()

    enabled = settings_for(tmp_path, computer_use_enabled=True, computer_session_ttl_seconds=120)
    sessions = ComputerSessionManager(enabled)
    started = sessions.start(60)
    assert started["active"] is True
    assert sessions.status(started["sessionId"])["active"] is True
    assert "sessionId" not in sessions.status(started["sessionId"])
    assert sessions.status("wrong-session")["active"] is False
    assert sessions.stop(started["sessionId"])["active"] is False
    assert sessions.status(started["sessionId"])["active"] is False


def test_audit_does_not_store_process_stdout_or_secret_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTMESH_TEST_PASSWORD", "SUPER-SECRET")
    settings = settings_for(tmp_path)
    catalog = ToolCatalog(settings, ProcessManager(settings), AuditLogger(settings.audit_file))
    catalog.run(
        "python-test",
        ["-c", "print('PRIVATE-STDOUT')"],
        str(settings.grants[0].path),
        wait_seconds=2.0,
    )
    audit_text = settings.audit_file.read_text(encoding="utf-8")
    assert "PRIVATE-STDOUT" not in audit_text
    assert "SUPER-SECRET" not in audit_text
    assert "test-token" not in audit_text


def test_app_close_without_pid_only_closes_instances_launched_by_bridge(tmp_path: Path):
    settings = settings_for(
        tmp_path,
        allowed_apps_json=json.dumps([
            {"id": "python-app", "displayName": "Python App", "executable": sys.executable}
        ]),
    )
    audit = AuditLogger(settings.audit_file)
    apps = AppCatalog(settings, audit)

    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    launched = apps.launch("python-app", ["-c", "import time; time.sleep(30)"])

    try:
        time.sleep(0.1)
        closed = apps.close("python-app")
        assert launched["pid"] in closed["closedPids"]
        assert unrelated.poll() is None, "bridge must not terminate an unrelated process sharing the same executable"
    finally:
        if unrelated.poll() is None:
            unrelated.terminate()
            try:
                unrelated.wait(timeout=3)
            except subprocess.TimeoutExpired:
                unrelated.kill()
                unrelated.wait(timeout=3)

