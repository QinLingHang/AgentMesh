from __future__ import annotations

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


async def _desktop_call(tool_name: str, arguments: dict[str, Any]) -> Any:
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
    if not settings.desktop_bridge_enabled:
        raise ToolError(ToolErrorType.UNAVAILABLE, "desktop bridge is disabled")
    if not settings.desktop_bridge_token:
        raise ToolError(ToolErrorType.PERMISSION_DENIED, "desktop bridge token is not configured")

    payload = dict(arguments)
    if tool_name == "local.ui.mouse.double_click":
        payload["clicks"] = 2
        payload["button"] = "left"
    elif tool_name == "local.ui.mouse.right_click":
        payload["clicks"] = 1
        payload["button"] = "right"

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
    request_timeout = max(
        float(settings.desktop_bridge_timeout_seconds),
        requested_wait + 3.0,
    )

    try:
        async with httpx.AsyncClient(
            timeout=request_timeout,
            trust_env=False,
        ) as client:
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
        raise ToolError(
            ToolErrorType.PERMISSION_DENIED,
            "desktop bridge denied the requested local operation",
        )
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
            "description": "Absolute path inside a folder explicitly authorized in AgentMesh Desktop Bridge.",
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
        _tool("local.fs.list", "List files and folders in an explicitly authorized local directory.", _path_schema({"limit": {"type": "integer"}})),
        _tool("local.fs.stat", "Read metadata for an explicitly authorized local file or folder.", _path_schema()),
        _tool("local.fs.read", "Read a text file from an explicitly authorized local directory.", _path_schema({"maxBytes": {"type": "integer"}})),
        _tool("local.fs.search", "Search file names and bounded text content under an explicitly authorized local directory.", _path_schema({"query": {"type": "string"}, "namePattern": {"type": "string"}, "recursive": {"type": "boolean"}, "maxResults": {"type": "integer"}})),
        _tool("local.fs.write", "Create or replace a UTF-8 text file in an explicitly authorized local directory.", _path_schema({"content": {"type": "string"}, "overwrite": {"type": "boolean"}, "createParents": {"type": "boolean"}}, ["content"]), "medium", True),
        _tool("local.fs.mkdir", "Create a folder in an explicitly authorized local directory.", _path_schema({"parents": {"type": "boolean"}}), "medium", True),
        _tool("local.fs.copy", "Copy a local file or folder between explicitly authorized locations.", transfer_schema, "medium", True),
        _tool("local.fs.move", "Move or rename a local file or folder between explicitly authorized locations.", transfer_schema, "high", True),
        _tool("local.fs.delete", "Delete a local file or folder from an explicitly authorized location.", _path_schema({"recursive": {"type": "boolean"}}), "high", True),
        # Applications
        _tool("local.app.list", "List local applications currently registered by Desktop Bridge.", _schema()),
        _tool("local.app.discover", "Rescan known Windows applications without launching them.", _schema()),
        _tool("local.app.launch", "Launch a registered local application. Application launch requires explicit approval.", _schema({"appId": {"type": "string"}, "args": {"type": "array"}}, ["appId"]), "medium", True),
        _tool("local.app.open", "Open an authorized local file/folder with a registered application.", _schema({"appId": {"type": "string"}, "path": {"type": "string"}}, ["appId", "path"]), "medium", True),
        _tool("local.app.status", "List currently running instances of registered local applications.", _schema({"appId": {"type": "string"}})),
        _tool("local.app.focus", "Bring a visible registered application window to the foreground.", app_schema),
        _tool("local.app.close", "Close a registered local application process. Unsaved work may be lost.", _schema({"appId": {"type": "string"}, "pid": {"type": "integer"}}, ["appId"]), "high", True),
        # CLI tools
        _tool("local.tool.list", "List registered local CLI tools such as Python, Git, Go, Node and FFmpeg.", _schema()),
        _tool("local.tool.discover", "Rescan the local PATH for approved known CLI tool families.", _schema()),
        _tool("local.tool.run", "Run a registered local CLI executable with argv and an authorized working directory. This is code execution and always requires approval.", _schema({"toolId": {"type": "string"}, "args": {"type": "array"}, "cwd": {"type": "string"}, "waitSeconds": {"type": "number"}}, ["toolId"]), "high", True),
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
        _tool("local.ui.keyboard.hotkey", "Send a bounded keyboard shortcut; dangerous system shortcuts are blocked by the bridge.", _session_schema({"keys": {"type": "array"}}, ["keys"]), "medium"),
        _tool("local.ui.wait", "Wait briefly for a local application UI to update.", _session_schema({"milliseconds": {"type": "integer"}}, ["milliseconds"])),
        _tool("local.ui.element.find", "Find Windows UI Automation elements by name/control type/automation id.", _session_schema({**selector_props, "limit": {"type": "integer"}}, ["handle"])),
        _tool("local.ui.element.click", "Click a Windows UI Automation element.", _session_schema(selector_props, ["handle"]), "medium"),
        _tool("local.ui.element.set_text", "Set text on a Windows UI Automation element without reading the clipboard.", _session_schema({**selector_props, "value": {"type": "string"}}, ["handle", "value"]), "medium"),
        _tool("local.ui.element.invoke", "Invoke a Windows UI Automation element action.", _session_schema(selector_props, ["handle"]), "medium"),
        _tool("local.ui.element.select", "Select a Windows UI Automation element or option.", _session_schema({**selector_props, "value": {"type": "string"}}, ["handle"]), "medium"),
    ]
    return definitions


def register_desktop_tools(registry: ToolRegistry) -> None:
    if not settings.desktop_bridge_enabled:
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
