from __future__ import annotations

import hmac
import os
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .audit import AuditLogger
from .computer import ComputerService, ComputerSessionManager
from .config import settings
from .executables import AppCatalog, ToolCatalog
from .filesystem import FileSystemService
from .policy import DesktopPermissionError
from .processes import ProcessManager


app = FastAPI(title="AgentMesh Desktop Bridge", version="2.0.0-dev")
audit = AuditLogger(settings.audit_file)
fs = FileSystemService(settings)
processes = ProcessManager(settings, audit)
apps = AppCatalog(settings, audit)
tools = ToolCatalog(settings, processes, audit)
sessions = ComputerSessionManager(settings, audit)
computer = ComputerService(settings, sessions, audit)


class PathRequest(BaseModel):
    path: str


class ListRequest(PathRequest):
    limit: int = Field(default=500, ge=1, le=500)


class ReadRequest(PathRequest):
    maxBytes: int | None = Field(default=None, ge=1)


class SearchRequest(PathRequest):
    query: str = ""
    namePattern: str = "*"
    recursive: bool = True
    maxResults: int | None = Field(default=None, ge=1)


class WriteRequest(PathRequest):
    content: str
    overwrite: bool = False
    createParents: bool = False


class MkdirRequest(PathRequest):
    parents: bool = True


class TransferRequest(BaseModel):
    source: str
    destination: str
    overwrite: bool = False


class DeleteRequest(PathRequest):
    recursive: bool = False


class AppRequest(BaseModel):
    appId: str


class AppStatusRequest(BaseModel):
    appId: str | None = None


class AppLaunchRequest(AppRequest):
    args: list[str] = Field(default_factory=list, max_length=32)


class AppOpenRequest(AppRequest):
    path: str


class AppCloseRequest(AppRequest):
    pid: int | None = Field(default=None, ge=1)


class ToolRunRequest(BaseModel):
    toolId: str
    args: list[str] = Field(default_factory=list, max_length=64)
    cwd: str | None = None
    waitSeconds: float = Field(default=0.0, ge=0.0, le=60.0)


class ProcessRequest(BaseModel):
    processId: str


class ProcessStatusRequest(ProcessRequest):
    waitSeconds: float = Field(default=0.0, ge=0.0, le=60.0)


class TerminalRunRequest(BaseModel):
    command: str = Field(min_length=1, max_length=8192)
    cwd: str | None = None
    waitSeconds: float = Field(default=0.0, ge=0.0, le=60.0)


class SessionStartRequest(BaseModel):
    durationSeconds: int | None = Field(default=None, ge=60, le=7200)


class SessionRequest(BaseModel):
    sessionId: str


class SessionStatusRequest(BaseModel):
    sessionId: str


class ScreenRequest(SessionRequest):
    pass


class WindowListRequest(SessionRequest):
    limit: int = Field(default=100, ge=1, le=100)


class WindowRequest(SessionRequest):
    handle: int


class MouseMoveRequest(SessionRequest):
    x: int
    y: int
    durationMs: int = Field(default=0, ge=0, le=5000)


class MouseClickRequest(SessionRequest):
    x: int
    y: int
    button: str = "left"
    clicks: int = Field(default=1, ge=1, le=2)


class MouseDragRequest(SessionRequest):
    startX: int
    startY: int
    endX: int
    endY: int
    durationMs: int = Field(default=300, ge=50, le=5000)


class MouseScrollRequest(SessionRequest):
    amount: int = Field(ge=-20, le=20)
    x: int | None = None
    y: int | None = None


class KeyboardTypeRequest(SessionRequest):
    text: str = Field(max_length=4000)
    intervalMs: int = Field(default=0, ge=0, le=500)


class KeyboardPressRequest(SessionRequest):
    key: str
    presses: int = Field(default=1, ge=1, le=20)


class KeyboardHotkeyRequest(SessionRequest):
    keys: list[str] = Field(min_length=1, max_length=4)


class WaitRequest(SessionRequest):
    milliseconds: int = Field(ge=0, le=10000)


class ElementSelectorRequest(WindowRequest):
    name: str = ""
    controlType: str = ""
    automationId: str = ""


class ElementFindRequest(ElementSelectorRequest):
    limit: int = Field(default=20, ge=1, le=50)


class ElementValueRequest(ElementSelectorRequest):
    value: str = Field(default="", max_length=4000)


def _authorize(token: str) -> None:
    if not settings.token:
        raise HTTPException(status_code=503, detail="desktop bridge token is not configured")
    if not hmac.compare_digest(token, settings.token):
        raise HTTPException(status_code=401, detail="invalid desktop bridge token")


def _run(operation_name: str, operation: Callable[[], Any], *, path_hints: list[str] | None = None):
    try:
        return operation()
    except DesktopPermissionError as exc:
        audit.failure(operation_name, exc, pathCount=len(path_hints or []))
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        audit.failure(operation_name, exc, pathCount=len(path_hints or []))
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, FileExistsError, IsADirectoryError, NotADirectoryError, OSError, RuntimeError) as exc:
        audit.failure(operation_name, exc, pathCount=len(path_hints or []))
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _terminal_argv(command: str) -> tuple[list[str], dict[str, Any]]:
    value = str(command or "")
    if not settings.allow_terminal:
        raise DesktopPermissionError("advanced terminal is disabled; set DESKTOP_ALLOW_TERMINAL=true")
    if os.name == "nt":
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", value], {
            "commandSha256": AuditLogger.digest_text(value),
            "commandLength": len(value),
            "shell": "powershell",
        }
    return ["/bin/sh", "-lc", value], {
        "commandSha256": AuditLogger.digest_text(value),
        "commandLength": len(value),
        "shell": "sh",
    }


@app.get("/health")
def health():
    return {
        "status": "ok" if settings.token and settings.grants else "not_configured",
        "service": "agentmesh-desktop-bridge",
        "authorizedRoots": len(settings.grants),
        "computerUseEnabled": settings.computer_use_enabled,
        "advancedTerminalEnabled": settings.allow_terminal,
    }


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
@app.post("/v1/files/list")
def list_files(req: ListRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("fs.list", lambda: fs.list(req.path, req.limit), path_hints=[req.path])


@app.post("/v1/files/stat")
def stat_file(req: PathRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("fs.stat", lambda: fs.stat(req.path), path_hints=[req.path])


@app.post("/v1/files/read")
def read_file(req: ReadRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("fs.read", lambda: fs.read(req.path, req.maxBytes), path_hints=[req.path])


@app.post("/v1/files/search")
def search_files(req: SearchRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("fs.search", lambda: fs.search(req.path, req.query, req.namePattern, req.recursive, req.maxResults), path_hints=[req.path])


@app.post("/v1/files/write")
def write_file(req: WriteRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("fs.write", lambda: fs.write(req.path, req.content, req.overwrite, req.createParents), path_hints=[req.path])


@app.post("/v1/files/mkdir")
def mkdir(req: MkdirRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("fs.mkdir", lambda: fs.mkdir(req.path, req.parents), path_hints=[req.path])


@app.post("/v1/files/copy")
def copy(req: TransferRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("fs.copy", lambda: fs.copy(req.source, req.destination, req.overwrite), path_hints=[req.source, req.destination])


@app.post("/v1/files/move")
def move(req: TransferRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("fs.move", lambda: fs.move(req.source, req.destination, req.overwrite), path_hints=[req.source, req.destination])


@app.post("/v1/files/delete")
def delete(req: DeleteRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("fs.delete", lambda: fs.delete(req.path, req.recursive), path_hints=[req.path])


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
@app.post("/v1/apps/list")
def app_list(x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return {"apps": apps.list()}


@app.post("/v1/apps/discover")
def app_discover(x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return {"apps": _run("app.discover", apps.refresh)}


@app.post("/v1/apps/launch")
def app_launch(req: AppLaunchRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("app.launch", lambda: apps.launch(req.appId, req.args))


@app.post("/v1/apps/open")
def app_open(req: AppOpenRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("app.open", lambda: apps.open(req.appId, req.path), path_hints=[req.path])


@app.post("/v1/apps/status")
def app_status(req: AppStatusRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("app.status", lambda: apps.status(req.appId))


@app.post("/v1/apps/focus")
def app_focus(req: AppRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("app.focus", lambda: apps.focus(req.appId))


@app.post("/v1/apps/close")
def app_close(req: AppCloseRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("app.close", lambda: apps.close(req.appId, req.pid))


# ---------------------------------------------------------------------------
# CLI tools and optional advanced terminal
# ---------------------------------------------------------------------------
@app.post("/v1/tools/list")
def tool_list(x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return {"tools": tools.list()}


@app.post("/v1/tools/discover")
def tool_discover(x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return {"tools": _run("tool.discover", tools.refresh)}


@app.post("/v1/tools/run")
def tool_run(req: ToolRunRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("tool.run", lambda: tools.run(req.toolId, req.args, req.cwd, req.waitSeconds), path_hints=[req.cwd or ""])


@app.post("/v1/tools/status")
def tool_status(req: ProcessStatusRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("tool.status", lambda: processes.wait(req.processId, req.waitSeconds))


@app.post("/v1/tools/cancel")
def tool_cancel(req: ProcessRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("tool.cancel", lambda: tools.cancel(req.processId))


@app.post("/v1/terminal/run")
def terminal_run(req: TerminalRunRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)

    def start():
        argv, detail = _terminal_argv(req.command)
        result = processes.start(
            kind="terminal",
            executable_id="advanced-terminal",
            argv=argv,
            cwd=req.cwd,
            audit_detail=detail,
        )
        return processes.wait(result["processId"], req.waitSeconds)

    return _run("terminal.run", start, path_hints=[req.cwd or ""])


@app.post("/v1/terminal/status")
def terminal_status(req: ProcessStatusRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("terminal.status", lambda: processes.wait(req.processId, req.waitSeconds))


@app.post("/v1/terminal/cancel")
def terminal_cancel(req: ProcessRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("terminal.cancel", lambda: processes.cancel(req.processId))


# ---------------------------------------------------------------------------
# Computer Use session + screen/window/mouse/keyboard/UIA
# ---------------------------------------------------------------------------
@app.post("/v1/ui/session/start")
def ui_session_start(req: SessionStartRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.session.start", lambda: sessions.start(req.durationSeconds))


@app.post("/v1/ui/session/status")
def ui_session_status(req: SessionStatusRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return sessions.status(req.sessionId)


@app.post("/v1/ui/session/stop")
def ui_session_stop(req: SessionRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.session.stop", lambda: sessions.stop(req.sessionId))


@app.post("/v1/ui/screen/capture")
def ui_screen_capture(req: ScreenRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.screen.capture", lambda: computer.capture(req.sessionId))


@app.post("/v1/ui/window/list")
def ui_window_list(req: WindowListRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.window.list", lambda: computer.window_list(req.sessionId, req.limit))


@app.post("/v1/ui/window/info")
def ui_window_info(req: WindowRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.window.info", lambda: computer.window_info(req.sessionId, req.handle))


@app.post("/v1/ui/window/focus")
def ui_window_focus(req: WindowRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.window.focus", lambda: computer.window_focus(req.sessionId, req.handle))


@app.post("/v1/ui/window/close")
def ui_window_close(req: WindowRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.window.close", lambda: computer.window_close(req.sessionId, req.handle))


@app.post("/v1/ui/mouse/move")
def ui_mouse_move(req: MouseMoveRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.mouse.move", lambda: computer.mouse_move(req.sessionId, req.x, req.y, req.durationMs))


@app.post("/v1/ui/mouse/click")
def ui_mouse_click(req: MouseClickRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.mouse.click", lambda: computer.mouse_click(req.sessionId, req.x, req.y, button=req.button, clicks=req.clicks))


@app.post("/v1/ui/mouse/drag")
def ui_mouse_drag(req: MouseDragRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.mouse.drag", lambda: computer.mouse_drag(req.sessionId, req.startX, req.startY, req.endX, req.endY, req.durationMs))


@app.post("/v1/ui/mouse/scroll")
def ui_mouse_scroll(req: MouseScrollRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.mouse.scroll", lambda: computer.mouse_scroll(req.sessionId, req.amount, req.x, req.y))


@app.post("/v1/ui/keyboard/type")
def ui_keyboard_type(req: KeyboardTypeRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.keyboard.type", lambda: computer.keyboard_type(req.sessionId, req.text, req.intervalMs))


@app.post("/v1/ui/keyboard/press")
def ui_keyboard_press(req: KeyboardPressRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.keyboard.press", lambda: computer.keyboard_press(req.sessionId, req.key, req.presses))


@app.post("/v1/ui/keyboard/hotkey")
def ui_keyboard_hotkey(req: KeyboardHotkeyRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.keyboard.hotkey", lambda: computer.keyboard_hotkey(req.sessionId, req.keys))


@app.post("/v1/ui/wait")
def ui_wait(req: WaitRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.wait", lambda: computer.wait(req.sessionId, req.milliseconds))


@app.post("/v1/ui/element/find")
def ui_element_find(req: ElementFindRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.element.find", lambda: computer.element_find(req.sessionId, req.handle, name=req.name, control_type=req.controlType, automation_id=req.automationId, limit=req.limit))


def _element_action(req: ElementValueRequest, action: str):
    return computer.element_action(
        req.sessionId,
        req.handle,
        name=req.name,
        control_type=req.controlType,
        automation_id=req.automationId,
        action=action,
        value=req.value,
    )


@app.post("/v1/ui/element/click")
def ui_element_click(req: ElementValueRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.element.click", lambda: _element_action(req, "click"))


@app.post("/v1/ui/element/set-text")
def ui_element_set_text(req: ElementValueRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.element.set_text", lambda: _element_action(req, "set_text"))


@app.post("/v1/ui/element/invoke")
def ui_element_invoke(req: ElementValueRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.element.invoke", lambda: _element_action(req, "invoke"))


@app.post("/v1/ui/element/select")
def ui_element_select(req: ElementValueRequest, x_desktop_token: str = Header(default="")):
    _authorize(x_desktop_token)
    return _run("ui.element.select", lambda: _element_action(req, "select"))
