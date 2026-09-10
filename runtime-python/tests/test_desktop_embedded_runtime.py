from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.tools import desktop


class _FakeFS:
    def __init__(self):
        self.calls = []

    def list(self, path, limit=500):
        self.calls.append((path, limit))
        return {"path": path, "entries": [], "truncated": False}


class _NeverCalled:
    def __getattr__(self, name):
        raise AssertionError(f"unexpected embedded service access: {name}")


def test_embedded_dispatch_reuses_desktop_filesystem_service(monkeypatch):
    fs = _FakeFS()
    services = {
        "settings": SimpleNamespace(allow_terminal=False),
        "audit": _NeverCalled(),
        "fs": fs,
        "processes": _NeverCalled(),
        "apps": _NeverCalled(),
        "tools": _NeverCalled(),
        "sessions": _NeverCalled(),
        "computer": _NeverCalled(),
        "permission_error": PermissionError,
    }
    monkeypatch.setattr(desktop, "_embedded_services", lambda: services)

    result = desktop._embedded_dispatch(
        "local.fs.list",
        {"path": r"C:\\AgentMesh", "limit": 17},
    )

    assert result["path"] == r"C:\\AgentMesh"
    assert fs.calls == [(r"C:\\AgentMesh", 17)]


def test_explicit_bridge_transport_still_wins_over_embedded(monkeypatch):
    monkeypatch.setattr(desktop.settings, "desktop_bridge_enabled", True)
    monkeypatch.setattr(desktop.settings, "desktop_embedded_enabled", True)

    async def bridge_call(name, arguments):
        return {"transport": "bridge", "name": name, "arguments": arguments}

    async def embedded_call(*_args, **_kwargs):
        raise AssertionError("embedded transport must not run when bridge is explicitly enabled")

    monkeypatch.setattr(desktop, "_desktop_bridge_call", bridge_call)
    monkeypatch.setattr(desktop, "_embedded_desktop_call", embedded_call)

    result = asyncio.run(desktop._desktop_call("local.fs.stat", {"path": r"C:\\x"}))
    assert result["transport"] == "bridge"


def test_desktop_tools_register_for_embedded_runtime(monkeypatch):
    monkeypatch.setattr(desktop, "_desktop_tools_available", lambda: True)

    class Registry:
        def __init__(self):
            self.names = []

        def register(self, definition, handler):
            self.names.append(definition.name)
            assert callable(handler)

    registry = Registry()
    desktop.register_desktop_tools(registry)

    assert "local.fs.list" in registry.names
    assert "local.fs.read" in registry.names
    assert "local.ui.session.start" in registry.names
    assert len(registry.names) == len(desktop.desktop_tool_definitions())
