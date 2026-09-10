from __future__ import annotations

import asyncio
import importlib
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.tools.contracts import ToolDefinition, ToolError, ToolErrorType
from app.tools.registry import ToolRegistry


_ENDPOINTS = {
    # Files
    "local.fs.list": "/v1/files/list",
    "local.fs.stat": "/v1/files/stat",
    "local.fs.read": "/v1/files/read",
    "local.fs.search": "/v1/files/search",
    "local.fs.write": "/v1/files/write",
    "local.fs.mkdir": "/v1/files/mkdir",
    "local.fs.copy": "/v1/files/copy",
    "local.fs.move": "/v1/files/move",
    "local.fs.delete": "/v1/files/delete",
    # Applications
    "local.app.list": "/v1/apps/list",
    "local.app.discover": "/v1/apps/discover",
    "local.app.launch": "/v1/apps/launch",
    "local.app.open": "/v1/apps/open",
    "local.app.status": "/v1/apps/status",
    "local.app.focus": "/v1/apps/focus",
    "local.app.close": "/v1/apps/close",
    # CLI tools
    "local.tool.list": "/v1/tools/list",
    "local.tool.discover": "/v1/tools/discover",
    "local.tool.run": "/v1/tools/run",
    "local.tool.status": "/v1/tools/status",
    "local.tool.cancel": "/v1/tools/cancel",
    # Advanced terminal
    "local.terminal.run": "/v1/terminal/run",
    "local.terminal.status": "/v1/terminal/status",
    "local.terminal.cancel": "/v1/terminal/cancel",
    # Computer Use session
    "local.ui.session.start": "/v1/ui/session/start",
    "local.ui.session.status": "/v1/ui/session/status",
    "local.ui.session.stop": "/v1/ui/session/stop",
    "local.ui.screen.capture": "/v1/ui/screen/capture",
    "local.ui.window.list": "/v1/ui/window/list",
    "local.ui.window.info": "/v1/ui/window/info",
    "local.ui.window.focus": "/v1/ui/window/focus",
    "local.ui.window.close": "/v1/ui/window/close",
    "local.ui.mouse.move": "/v1/ui/mouse/move",
    "local.ui.mouse.click": "/v1/ui/mouse/click",
    "local.ui.mouse.double_click": "/v1/ui/mouse/click",
    "local.ui.mouse.right_click": "/v1/ui/mouse/click",
    "local.ui.mouse.drag": "/v1/ui/mouse/drag",
    "local.ui.mouse.scroll": "/v1/ui/mouse/scroll",
    "local.ui.keyboard.type": "/v1/ui/keyboard/type",
    "local.ui.keyboard.press": "/v1/ui/keyboard/press",
    "local.ui.keyboard.hotkey": "/v1/ui/keyboard/hotkey",
    "local.ui.wait": "/v1/ui/wait",
    "local.ui.element.find": "/v1/ui/element/find",
    "local.ui.element.click": "/v1/ui/element/click",
    "local.ui.element.set_text": "/v1/ui/element/set-text",
    "local.ui.element.invoke": "/v1/ui/element/invoke",
    "local.ui.element.select": "/v1/ui/element/select",
}


def is_desktop_tool_name(name: str) -> bool:
    return str(name or "").strip().lower().startswith("local.")


def is_desktop_screenshot_tool(name: str) -> bool:
    return str(name or "").strip().lower() == "local.ui.screen.capture"


def desktop_screenshot_attachment(result: Any):
    """Return a request-local model image attachment plus metadata-only result.

    Screenshot bytes must never be copied into trace/tool-message JSON. The caller
    can attach the returned base64 bytes to the *next* model turn so the selected
    vision model actually sees the desktop.
    """
    if not isinstance(result, dict):
        return None, result
    image_base64 = result.get("imageBase64")
    media_type = result.get("mediaType")
    if not isinstance(image_base64, str) or not image_base64 or not isinstance(media_type, str):
        return None, result

    from app.models import ModelInputAttachment

    metadata = {key: value for key, value in result.items() if key != "imageBase64"}
    attachment = ModelInputAttachment(
        name="agentmesh-desktop.png",
        media_type=media_type,
        content_base64=image_base64,
    )
    return attachment, metadata


def _normalize_payload(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    payload = dict(arguments)
    if tool_name == "local.ui.mouse.double_click":
        payload["clicks"] = 2
        payload["button"] = "left"
    elif tool_name == "local.ui.mouse.right_click":
        payload["clicks"] = 1
        payload["button"] = "right"
    return payload


def _embedded_desktop_selected() -> bool:
    return bool(
        settings.desktop_embedded_enabled
        and os.name == "nt"
        and not settings.desktop_bridge_enabled
    )


def _desktop_tools_available() -> bool:
    # Remote/restricted bridge stays authoritative when explicitly enabled.
    # Otherwise Windows Runtime exposes the same local.* tools in-process.
    return bool(settings.desktop_bridge_enabled or _embedded_desktop_selected())


@lru_cache(maxsize=1)
def _embedded_services() -> dict[str, Any]:
    """Load Desktop capability as a library inside Runtime, without HTTP.

    desktop-bridge remains a standalone optional service for remote/restricted
    nodes. In local Windows mode we reuse the exact same policy/services in the
    Runtime process so safety rules do not fork between the two transports.
    """
    if not _embedded_desktop_selected():
        raise ToolError(ToolErrorType.UNAVAILABLE, "embedded desktop runtime is disabled")

    repo_root = Path(__file__).resolve().parents[3]
    package_root = repo_root / "desktop-bridge"
    if not package_root.is_dir():
        raise ToolError(
            ToolErrorType.UNAVAILABLE,
            "embedded desktop package is missing from this AgentMesh source tree",
        )

    package_path = str(package_root)
    if package_path not in sys.path:
        sys.path.insert(0, package_path)

    try:
        audit_module = importlib.import_module("desktop_bridge.audit")
        computer_module = importlib.import_module("desktop_bridge.computer")
        config_module = importlib.import_module("desktop_bridge.config")
        executables_module = importlib.import_module("desktop_bridge.executables")
        filesystem_module = importlib.import_module("desktop_bridge.filesystem")
        policy_module = importlib.import_module("desktop_bridge.policy")
        processes_module = importlib.import_module("desktop_bridge.processes")
    except ImportError as exc:
        raise ToolError(
            ToolErrorType.UNAVAILABLE,
            "embedded desktop dependencies are unavailable; install runtime-python/requirements-desktop.txt",
        ) from exc

    desktop_settings = config_module.load_settings()
    audit = audit_module.AuditLogger(desktop_settings.audit_file)
    processes = processes_module.ProcessManager(desktop_settings, audit)
    apps = executables_module.AppCatalog(desktop_settings, audit)
    tools = executables_module.ToolCatalog(desktop_settings, processes, audit)
    sessions = computer_module.ComputerSessionManager(desktop_settings, audit)
    computer = computer_module.ComputerService(desktop_settings, sessions, audit)
    filesystem = filesystem_module.FileSystemService(desktop_settings)

    return {
        "settings": desktop_settings,
        "audit": audit,
        "fs": filesystem,
        "processes": processes,
        "apps": apps,
        "tools": tools,
        "sessions": sessions,
        "computer": computer,
        "permission_error": policy_module.DesktopPermissionError,
    }


def _embedded_terminal_argv(services: dict[str, Any], command: str) -> tuple[list[str], dict[str, Any]]:
    value = str(command or "")
    desktop_settings = services["settings"]
    if not desktop_settings.allow_terminal:
        raise services["permission_error"](
            "advanced terminal is disabled; set DESKTOP_ALLOW_TERMINAL=true"
        )
    if os.name == "nt":
        argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", value]
        shell = "powershell"
    else:
        argv = ["/bin/sh", "-lc", value]
        shell = "sh"
    return argv, {
        "commandSha256": services["audit"].digest_text(value),
        "commandLength": len(value),
        "shell": shell,
    }


def _embedded_dispatch(tool_name: str, payload: dict[str, Any]) -> Any:
    services = _embedded_services()
    fs = services["fs"]
    processes = services["processes"]
    apps = services["apps"]
    tools = services["tools"]
    sessions = services["sessions"]
    computer = services["computer"]

    if tool_name == "local.fs.list":
        return fs.list(payload["path"], payload.get("limit", 500))
    if tool_name == "local.fs.stat":
        return fs.stat(payload["path"])
    if tool_name == "local.fs.read":
        return fs.read(payload["path"], payload.get("maxBytes"))
    if tool_name == "local.fs.search":
        return fs.search(
            payload["path"],
            payload.get("query", ""),
            payload.get("namePattern", "*"),
            payload.get("recursive", True),
            payload.get("maxResults"),
        )
    if tool_name == "local.fs.write":
        return fs.write(
            payload["path"],
            payload["content"],
            payload.get("overwrite", False),
            payload.get("createParents", False),
        )
    if tool_name == "local.fs.mkdir":
        return fs.mkdir(payload["path"], payload.get("parents", True))
    if tool_name == "local.fs.copy":
        return fs.copy(payload["source"], payload["destination"], payload.get("overwrite", False))
    if tool_name == "local.fs.move":
        return fs.move(payload["source"], payload["destination"], payload.get("overwrite", False))
    if tool_name == "local.fs.delete":
        return fs.delete(payload["path"], payload.get("recursive", False))

    if tool_name == "local.app.list":
        return {"apps": apps.list()}
    if tool_name == "local.app.discover":
        return {"apps": apps.refresh()}
    if tool_name == "local.app.launch":
        return apps.launch(payload["appId"], payload.get("args", []))
    if tool_name == "local.app.open":
        return apps.open(payload["appId"], payload["path"])
    if tool_name == "local.app.status":
        return apps.status(payload.get("appId"))
    if tool_name == "local.app.focus":
        return apps.focus(payload["appId"])
    if tool_name == "local.app.close":
        return apps.close(payload["appId"], payload.get("pid"))

    if tool_name == "local.tool.list":
        return {"tools": tools.list()}
    if tool_name == "local.tool.discover":
        return {"tools": tools.refresh()}
    if tool_name == "local.tool.run":
        return tools.run(
            payload["toolId"],
            payload.get("args", []),
            payload.get("cwd"),
            float(payload.get("waitSeconds") or 0.0),
        )
    if tool_name == "local.tool.status":
        return processes.wait(payload["processId"], float(payload.get("waitSeconds") or 0.0))
    if tool_name == "local.tool.cancel":
        return tools.cancel(payload["processId"])

    if tool_name == "local.terminal.run":
        argv, detail = _embedded_terminal_argv(services, payload["command"])
        result = processes.start(
            kind="terminal",
            executable_id="advanced-terminal",
            argv=argv,
            cwd=payload.get("cwd"),
            audit_detail=detail,
        )
        return processes.wait(result["processId"], float(payload.get("waitSeconds") or 0.0))
    if tool_name == "local.terminal.status":
        return processes.wait(payload["processId"], float(payload.get("waitSeconds") or 0.0))
    if tool_name == "local.terminal.cancel":
        return processes.cancel(payload["processId"])

    if tool_name == "local.ui.session.start":
        return sessions.start(payload.get("durationSeconds"))
    if tool_name == "local.ui.session.status":
        return sessions.status(payload["sessionId"])
    if tool_name == "local.ui.session.stop":
        return sessions.stop(payload["sessionId"])
    if tool_name == "local.ui.screen.capture":
        return computer.capture(payload["sessionId"])
    if tool_name == "local.ui.window.list":
        return computer.window_list(payload["sessionId"], payload.get("limit", 100))
    if tool_name == "local.ui.window.info":
        return computer.window_info(payload["sessionId"], int(payload["handle"]))
    if tool_name == "local.ui.window.focus":
        return computer.window_focus(payload["sessionId"], int(payload["handle"]))
    if tool_name == "local.ui.window.close":
        return computer.window_close(payload["sessionId"], int(payload["handle"]))
    if tool_name == "local.ui.mouse.move":
        return computer.mouse_move(
            payload["sessionId"], int(payload["x"]), int(payload["y"]), int(payload.get("durationMs") or 0)
        )
    if tool_name in {"local.ui.mouse.click", "local.ui.mouse.double_click", "local.ui.mouse.right_click"}:
        return computer.mouse_click(
            payload["sessionId"],
            int(payload["x"]),
            int(payload["y"]),
            button=str(payload.get("button") or "left"),
            clicks=int(payload.get("clicks") or 1),
        )
    if tool_name == "local.ui.mouse.drag":
        return computer.mouse_drag(
            payload["sessionId"], int(payload["startX"]), int(payload["startY"]),
            int(payload["endX"]), int(payload["endY"]), int(payload.get("durationMs") or 300),
        )
    if tool_name == "local.ui.mouse.scroll":
        return computer.mouse_scroll(
            payload["sessionId"], int(payload["amount"]), payload.get("x"), payload.get("y")
        )
    if tool_name == "local.ui.keyboard.type":
        return computer.keyboard_type(
            payload["sessionId"], str(payload["text"]), int(payload.get("intervalMs") or 0)
        )
    if tool_name == "local.ui.keyboard.press":
        return computer.keyboard_press(
            payload["sessionId"], str(payload["key"]), int(payload.get("presses") or 1)
        )
    if tool_name == "local.ui.keyboard.hotkey":
        return computer.keyboard_hotkey(payload["sessionId"], list(payload["keys"]))
    if tool_name == "local.ui.wait":
        return computer.wait(payload["sessionId"], int(payload["milliseconds"]))
    if tool_name == "local.ui.element.find":
        return computer.element_find(
            payload["sessionId"], int(payload["handle"]),
            name=str(payload.get("name") or ""),
            control_type=str(payload.get("controlType") or ""),
            automation_id=str(payload.get("automationId") or ""),
            limit=int(payload.get("limit") or 20),
        )
    if tool_name in {
        "local.ui.element.click",
        "local.ui.element.set_text",
        "local.ui.element.invoke",
        "local.ui.element.select",
    }:
        action = {
            "local.ui.element.click": "click",
            "local.ui.element.set_text": "set_text",
            "local.ui.element.invoke": "invoke",
            "local.ui.element.select": "select",
        }[tool_name]
        return computer.element_action(
            payload["sessionId"], int(payload["handle"]),
            name=str(payload.get("name") or ""),
            control_type=str(payload.get("controlType") or ""),
            automation_id=str(payload.get("automationId") or ""),
            action=action,
            value=str(payload.get("value") or ""),
        )

    raise ToolError(ToolErrorType.NOT_FOUND, f"unsupported desktop tool: {tool_name}")


async def _embedded_desktop_call(tool_name: str, arguments: dict[str, Any]) -> Any:
    payload = _normalize_payload(tool_name, arguments)
    try:
        return await asyncio.to_thread(_embedded_dispatch, tool_name, payload)
    except ToolError:
        raise
    except Exception as exc:
        try:
            permission_error = _embedded_services()["permission_error"]
        except ToolError:
            raise
        if isinstance(exc, permission_error):
            raise ToolError(ToolErrorType.PERMISSION_DENIED, str(exc)) from exc
        if isinstance(exc, FileNotFoundError):
            raise ToolError(ToolErrorType.NOT_FOUND, "local resource was not found") from exc
        if isinstance(exc, (ValueError, FileExistsError, IsADirectoryError, NotADirectoryError)):
            raise ToolError(ToolErrorType.INVALID_ARGUMENTS, str(exc)) from exc
        if isinstance(exc, RuntimeError):
            message = str(exc)
            lowered = message.casefold()
            if "disabled" in lowered:
                raise ToolError(ToolErrorType.PERMISSION_DENIED, message) from exc
            if "required" in lowered or "unavailable" in lowered:
                raise ToolError(ToolErrorType.UNAVAILABLE, message) from exc
        raise ToolError(ToolErrorType.EXECUTION_FAILED, "local desktop operation failed") from exc


async def _desktop_bridge_call(tool_name: str, arguments: dict[str, Any]) -> Any:
    base_url = settings.desktop_bridge_base_url.rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").casefold() not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ToolError(
            ToolErrorType.PERMISSION_DENIED,
            "desktop bridge base URL must use a loopback host",
        )

    endpoint = _ENDPOINTS.get(tool_name)
    if not endpoint:
        raise ToolError(ToolErrorType.NOT_FOUND, f"unsupported desktop tool: {tool_name}")
    if not settings.desktop_bridge_token:
        raise ToolError(ToolErrorType.PERMISSION_DENIED, "desktop bridge token is not configured")

    payload = _normalize_payload(tool_name, arguments)
    requested_wait = 0.0
    if tool_name in {
        "local.tool.run",
        "local.tool.status",
        "local.terminal.run",
        "local.terminal.status",
    }:
        try:
            requested_wait = max(0.0, min(60.0, float(payload.get("waitSeconds") or 0.0)))
        except (TypeError, ValueError):
            requested_wait = 0.0
    request_timeout = max(float(settings.desktop_bridge_timeout_seconds), requested_wait + 3.0)

    try:
        async with httpx.AsyncClient(timeout=request_timeout, trust_env=False) as client:
            response = await client.post(
                f"{base_url}{endpoint}",
                json=payload,
                headers={"x-desktop-token": settings.desktop_bridge_token},
            )
    except httpx.TimeoutException as exc:
        raise ToolError(ToolErrorType.TIMEOUT, "desktop bridge timed out") from exc
    except httpx.RequestError as exc:
        raise ToolError(ToolErrorType.UNAVAILABLE, "desktop bridge is unavailable") from exc

    if response.status_code in {401, 403}:
        raise ToolError(ToolErrorType.PERMISSION_DENIED, "desktop bridge denied the requested local operation")
    if response.status_code == 404:
        raise ToolError(ToolErrorType.NOT_FOUND, "local resource was not found")
    if response.status_code // 100 != 2:
        detail = "desktop bridge rejected the operation"
        try:
            body = response.json()
            if isinstance(body, dict) and body.get("detail"):
                detail = str(body["detail"])
        except ValueError:
            pass
        raise ToolError(ToolErrorType.INVALID_ARGUMENTS, detail)

    try:
        return response.json()
    except ValueError as exc:
        raise ToolError(ToolErrorType.EXECUTION_FAILED, "desktop bridge returned invalid JSON") from exc


async def _desktop_call(tool_name: str, arguments: dict[str, Any]) -> Any:
    if settings.desktop_bridge_enabled:
        return await _desktop_bridge_call(tool_name, arguments)
    if _embedded_desktop_selected():
        return await _embedded_desktop_call(tool_name, arguments)
    raise ToolError(ToolErrorType.UNAVAILABLE, "local desktop capability is disabled")


def _handler(name: str):
    async def execute(arguments: dict[str, Any]) -> Any:
        return await _desktop_call(name, arguments)

    return execute


def _schema(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


def _path_schema(extra: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "path": {
            "type": "string",
            "description": "Absolute local path. In Local Computer Mode, normal files on fixed drives are available subject to Desktop safety policy; sensitive/system paths remain protected.",
        }
    }
    properties.update(extra or {})
    return _schema(properties, ["path", *(required or [])])


def _session_props(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    value = {
        "sessionId": {
            "type": "string",
            "description": "Active computer-use session id returned by local.ui.session.start.",
        }
    }
    value.update(extra or {})
    return value


def _session_schema(extra: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return _schema(_session_props(extra), ["sessionId", *(required or [])])


def _tool(name: str, description: str, schema: dict[str, Any], risk: str = "low", confirm: bool = False) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        inputSchema=schema,
        riskLevel=risk,
        requiresConfirmation=confirm,
    )


def desktop_tool_definitions() -> list[ToolDefinition]:
    transfer_schema = _schema(
        {
            "source": {"type": "string"},
            "destination": {"type": "string"},
            "overwrite": {"type": "boolean"},
        },
        ["source", "destination"],
    )
    process_schema = _schema({"processId": {"type": "string"}}, ["processId"])
    process_status_schema = _schema(
        {"processId": {"type": "string"}, "waitSeconds": {"type": "number"}},
        ["processId"],
    )
    app_schema = _schema({"appId": {"type": "string"}}, ["appId"])
    selector_props = {
        "handle": {"type": "integer"},
        "name": {"type": "string"},
        "controlType": {"type": "string"},
        "automationId": {"type": "string"},
    }

    definitions = [
        # Files
        _tool("local.fs.list", "List files and folders on the local computer when allowed by Desktop safety policy.", _path_schema({"limit": {"type": "integer"}})),
        _tool("local.fs.stat", "Read metadata for a local file or folder when allowed by Desktop safety policy.", _path_schema()),
        _tool("local.fs.read", "Read a normal local text file directly; sensitive/system paths remain protected.", _path_schema({"maxBytes": {"type": "integer"}})),
        _tool("local.fs.search", "Search file names and bounded text content on the local computer within Desktop safety limits.", _path_schema({"query": {"type": "string"}, "namePattern": {"type": "string"}, "recursive": {"type": "boolean"}, "maxResults": {"type": "integer"}})),
        _tool("local.fs.write", "Create or replace a UTF-8 text file on the local computer. Mutation requires explicit approval.", _path_schema({"content": {"type": "string"}, "overwrite": {"type": "boolean"}, "createParents": {"type": "boolean"}}, ["content"]), "medium", True),
        _tool("local.fs.mkdir", "Create a local folder. Mutation requires explicit approval.", _path_schema({"parents": {"type": "boolean"}}), "medium", True),
        _tool("local.fs.copy", "Copy a local file or folder between policy-allowed locations. Mutation requires explicit approval.", transfer_schema, "medium", True),
        _tool("local.fs.move", "Move or rename a local file or folder between policy-allowed locations. This is high risk and requires approval.", transfer_schema, "high", True),
        _tool("local.fs.delete", "Delete a local file or folder from a policy-allowed location. This is high risk and requires approval.", _path_schema({"recursive": {"type": "boolean"}}), "high", True),
        # Applications
        _tool("local.app.list", "List local applications registered by the local desktop runtime.", _schema()),
        _tool("local.app.discover", "Rescan known Windows applications without launching them.", _schema()),
        _tool("local.app.launch", "Launch a registered local application. Application launch requires explicit approval.", _schema({"appId": {"type": "string"}, "args": {"type": "array"}}, ["appId"]), "medium", True),
        _tool("local.app.open", "Open a policy-allowed local file/folder with a registered application.", _schema({"appId": {"type": "string"}, "path": {"type": "string"}}, ["appId", "path"]), "medium", True),
        _tool("local.app.status", "List currently running instances of registered local applications.", _schema({"appId": {"type": "string"}})),
        _tool("local.app.focus", "Bring a visible registered application window to the foreground.", app_schema),
        _tool("local.app.close", "Close a registered local application process. Unsaved work may be lost.", _schema({"appId": {"type": "string"}, "pid": {"type": "integer"}}, ["appId"]), "high", True),
        # CLI tools
        _tool("local.tool.list", "List registered local CLI tools such as Python, Git, Go, Node and FFmpeg.", _schema()),
        _tool("local.tool.discover", "Rescan the local PATH for approved known CLI tool families.", _schema()),
        _tool("local.tool.run", "Run a registered local CLI executable with argv and a policy-allowed working directory. This is code execution and always requires approval.", _schema({"toolId": {"type": "string"}, "args": {"type": "array"}, "cwd": {"type": "string"}, "waitSeconds": {"type": "number"}}, ["toolId"]), "high", True),
        _tool("local.tool.status", "Wait briefly for, then read bounded stdout/stderr and status for a process started by local.tool.run.", process_status_schema),
        _tool("local.tool.cancel", "Cancel a process started by local.tool.run.", process_schema, "medium", True),
        # Advanced terminal
        _tool("local.terminal.run", "Run an arbitrary terminal command only when the user explicitly enables advanced terminal mode. Always high risk and approved per action.", _schema({"command": {"type": "string"}, "cwd": {"type": "string"}, "waitSeconds": {"type": "number"}}, ["command"]), "high", True),
        _tool("local.terminal.status", "Wait briefly for, then read bounded output/status for an approved advanced terminal process.", process_status_schema),
        _tool("local.terminal.cancel", "Cancel an approved advanced terminal process.", process_schema, "high", True),
        # Computer Use session
        _tool("local.ui.session.start", "Start a time-bounded local Computer Use session. This explicit grant gates screen, window, mouse, keyboard and UI Automation actions.", _schema({"durationSeconds": {"type": "integer"}}), "high", True),
        _tool("local.ui.session.status", "Check whether a known local Computer Use session is still active.", _schema({"sessionId": {"type": "string"}}, ["sessionId"])),
        _tool("local.ui.session.stop", "Immediately stop the active local Computer Use session.", _session_schema()),
        _tool("local.ui.screen.capture", "Capture the current desktop for visual reasoning. Screenshot bytes are transported request-locally to the vision model and omitted from trace.", _session_schema()),
        _tool("local.ui.window.list", "List visible Windows desktop windows in an active Computer Use session.", _session_schema({"limit": {"type": "integer"}})),
        _tool("local.ui.window.info", "Read metadata for a visible desktop window.", _session_schema({"handle": {"type": "integer"}}, ["handle"])),
        _tool("local.ui.window.focus", "Focus a visible desktop window.", _session_schema({"handle": {"type": "integer"}}, ["handle"]), "medium"),
        _tool("local.ui.window.close", "Close a visible desktop window. Unsaved work may be lost.", _session_schema({"handle": {"type": "integer"}}, ["handle"]), "high", True),
        _tool("local.ui.mouse.move", "Move the mouse pointer inside the current desktop.", _session_schema({"x": {"type": "integer"}, "y": {"type": "integer"}, "durationMs": {"type": "integer"}}, ["x", "y"]), "medium"),
        _tool("local.ui.mouse.click", "Click the mouse in an active Computer Use session.", _session_schema({"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string"}, "clicks": {"type": "integer"}}, ["x", "y"]), "medium"),
        _tool("local.ui.mouse.double_click", "Double-click the left mouse button in an active Computer Use session.", _session_schema({"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"]), "medium"),
        _tool("local.ui.mouse.right_click", "Right-click the mouse in an active Computer Use session.", _session_schema({"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"]), "medium"),
        _tool("local.ui.mouse.drag", "Drag with the left mouse button between desktop coordinates.", _session_schema({"startX": {"type": "integer"}, "startY": {"type": "integer"}, "endX": {"type": "integer"}, "endY": {"type": "integer"}, "durationMs": {"type": "integer"}}, ["startX", "startY", "endX", "endY"]), "medium"),
        _tool("local.ui.mouse.scroll", "Scroll the current desktop view.", _session_schema({"amount": {"type": "integer"}, "x": {"type": "integer"}, "y": {"type": "integer"}}, ["amount"]), "medium"),
        _tool("local.ui.keyboard.type", "Type text into the focused UI without using the clipboard.", _session_schema({"text": {"type": "string"}, "intervalMs": {"type": "integer"}}, ["text"]), "medium"),
        _tool("local.ui.keyboard.press", "Press a keyboard key in an active Computer Use session.", _session_schema({"key": {"type": "string"}, "presses": {"type": "integer"}}, ["key"]), "medium"),
        _tool("local.ui.keyboard.hotkey", "Send a bounded keyboard shortcut; dangerous system shortcuts are blocked by Desktop safety policy.", _session_schema({"keys": {"type": "array"}}, ["keys"]), "medium"),
        _tool("local.ui.wait", "Wait briefly for a local application UI to update.", _session_schema({"milliseconds": {"type": "integer"}}, ["milliseconds"])),
        _tool("local.ui.element.find", "Find Windows UI Automation elements by name/control type/automation id.", _session_schema({**selector_props, "limit": {"type": "integer"}}, ["handle"])),
        _tool("local.ui.element.click", "Click a Windows UI Automation element.", _session_schema(selector_props, ["handle"]), "medium"),
        _tool("local.ui.element.set_text", "Set text on a Windows UI Automation element without reading the clipboard.", _session_schema({**selector_props, "value": {"type": "string"}}, ["handle", "value"]), "medium"),
        _tool("local.ui.element.invoke", "Invoke a Windows UI Automation element action.", _session_schema(selector_props, ["handle"]), "medium"),
        _tool("local.ui.element.select", "Select a Windows UI Automation element or option.", _session_schema({**selector_props, "value": {"type": "string"}}, ["handle"]), "medium"),
    ]
    return definitions


def register_desktop_tools(registry: ToolRegistry) -> None:
    if not _desktop_tools_available():
        return
    for tool in desktop_tool_definitions():
        registry.register(tool, _handler(tool.name))


def desktop_trace_arguments(tool_name: str, arguments: Any) -> Any:
    if not is_desktop_tool_name(tool_name) or not isinstance(arguments, dict):
        return arguments
    value = dict(arguments)
    if isinstance(value.get("sessionId"), str):
        value["sessionId"] = "[SESSION]"
    if tool_name == "local.fs.write" and isinstance(value.get("content"), str):
        value["content"] = f"[CONTENT {len(value['content'])} chars]"
    if tool_name == "local.terminal.run" and isinstance(value.get("command"), str):
        import hashlib
        command = value["command"]
        value["command"] = {
            "sha256": hashlib.sha256(command.encode("utf-8", errors="replace")).hexdigest(),
            "length": len(command),
        }
    if tool_name in {"local.ui.keyboard.type", "local.ui.element.set_text"}:
        key = "text" if tool_name.endswith("keyboard.type") else "value"
        if isinstance(value.get(key), str):
            value[key] = f"[TEXT {len(value[key])} chars]"
    if tool_name == "local.tool.run" and isinstance(value.get("args"), list):
        value["args"] = f"[ARGV {len(value['args'])} items]"
    return value


def desktop_trace_result(tool_name: str, result: Any) -> Any:
    if not is_desktop_tool_name(tool_name) or not isinstance(result, dict):
        return result
    value = dict(result)
    value.pop("imageBase64", None)
    if "sessionId" in value:
        value["sessionId"] = "[SESSION]"
    if tool_name == "local.fs.read" and isinstance(value.get("content"), str):
        value["contentChars"] = len(value["content"])
        value.pop("content", None)
    if tool_name == "local.fs.search" and isinstance(value.get("results"), list):
        cleaned = []
        for item in value["results"][:100]:
            if isinstance(item, dict):
                copy = dict(item)
                copy.pop("preview", None)
                cleaned.append(copy)
        value["results"] = cleaned
    for key in ("stdout", "stderr"):
        if isinstance(value.get(key), str):
            value[f"{key}Chars"] = len(value[key])
            value.pop(key, None)
    return value
