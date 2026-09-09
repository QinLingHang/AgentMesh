from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audit import AuditLogger
from .config import Settings
from .policy import PathPolicy
from .processes import ProcessManager, safe_environment


@dataclass(frozen=True, slots=True)
class ExecutableEntry:
    id: str
    display_name: str
    executable: str
    source: str
    batch_wrapper: bool = False


KNOWN_TOOLS: dict[str, tuple[str, tuple[str, ...]]] = {
    "python": ("Python", ("python.exe", "python3.exe", "python", "python3")),
    "git": ("Git", ("git.exe", "git")),
    "go": ("Go", ("go.exe", "go")),
    "java": ("Java", ("java.exe", "java")),
    "javac": ("Java Compiler", ("javac.exe", "javac")),
    "node": ("Node.js", ("node.exe", "node")),
    "npm": ("npm", ("npm.cmd", "npm")),
    "pnpm": ("pnpm", ("pnpm.cmd", "pnpm")),
    "yarn": ("Yarn", ("yarn.cmd", "yarn")),
    "ffmpeg": ("FFmpeg", ("ffmpeg.exe", "ffmpeg")),
    "ffprobe": ("FFprobe", ("ffprobe.exe", "ffprobe")),
    "docker": ("Docker CLI", ("docker.exe", "docker")),
    "maven": ("Maven", ("mvn.cmd", "mvn")),
    "gradle": ("Gradle", ("gradle.bat", "gradle")),
}

KNOWN_APPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "vscode": ("Visual Studio Code", ("Code.exe",)),
    "chrome": ("Google Chrome", ("chrome.exe",)),
    "edge": ("Microsoft Edge", ("msedge.exe",)),
    "notepad": ("记事本", ("notepad.exe",)),
    "explorer": ("文件资源管理器", ("explorer.exe",)),
    "word": ("Microsoft Word", ("WINWORD.EXE",)),
    "excel": ("Microsoft Excel", ("EXCEL.EXE",)),
    "powerpoint": ("Microsoft PowerPoint", ("POWERPNT.EXE",)),
    "pycharm": ("PyCharm", ("pycharm64.exe",)),
    "idea": ("IntelliJ IDEA", ("idea64.exe",)),
    "capcut": ("剪映 / CapCut", ("JianyingPro.exe", "CapCut.exe")),
}


def _registry_app_path(executable_name: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:
        return None
    subkey = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0)):
            try:
                with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | view) as key:
                    value, _ = winreg.QueryValueEx(key, None)
                    if value and Path(value).exists():
                        return str(Path(value))
            except OSError:
                continue
    return None


def _find_known(executable_names: tuple[str, ...], *, app: bool) -> str | None:
    for name in executable_names:
        found = shutil.which(name)
        if found:
            return found
        if app:
            found = _registry_app_path(name)
            if found:
                return found
    return None


def _configured_entries(raw_json: str, source: str) -> list[ExecutableEntry]:
    try:
        payload = json.loads(raw_json or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{source} JSON must be valid") from exc
    if not isinstance(payload, list):
        raise RuntimeError(f"{source} JSON must be an array")
    result: list[ExecutableEntry] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise RuntimeError(f"{source} item #{index + 1} must be an object")
        entry_id = str(item.get("id") or "").strip().lower()
        executable = str(item.get("executable") or "").strip()
        display_name = str(item.get("displayName") or entry_id).strip()
        if not entry_id or not executable:
            raise RuntimeError(f"{source} item #{index + 1} requires id and executable")
        resolved = shutil.which(executable) or executable
        if not Path(resolved).exists() and shutil.which(resolved) is None:
            continue
        result.append(
            ExecutableEntry(
                id=entry_id,
                display_name=display_name or entry_id,
                executable=str(resolved),
                source="configured",
                batch_wrapper=str(resolved).lower().endswith((".cmd", ".bat")),
            )
        )
    return result


class ToolCatalog:
    def __init__(self, settings: Settings, processes: ProcessManager, audit: AuditLogger | None = None):
        self.settings = settings
        self.processes = processes
        self.audit = audit or AuditLogger(settings.audit_file)
        self._entries: dict[str, ExecutableEntry] = {}
        self.refresh()

    def refresh(self) -> list[dict[str, Any]]:
        entries: dict[str, ExecutableEntry] = {}
        if self.settings.auto_discover_executables:
            for entry_id, (display_name, names) in KNOWN_TOOLS.items():
                found = _find_known(names, app=False)
                if found:
                    entries[entry_id] = ExecutableEntry(
                        id=entry_id,
                        display_name=display_name,
                        executable=found,
                        source="discovered",
                        batch_wrapper=found.lower().endswith((".cmd", ".bat")),
                    )
        for entry in _configured_entries(self.settings.allowed_tools_json, "DESKTOP_ALLOWED_TOOLS_JSON"):
            entries[entry.id] = entry
        self._entries = entries
        self.audit.write("tool.discover", ok=True, detail={"count": len(entries)})
        return self.list()

    def list(self) -> list[dict[str, Any]]:
        return [
            {"id": item.id, "displayName": item.display_name, "executable": item.executable, "source": item.source}
            for item in sorted(self._entries.values(), key=lambda value: value.id)
        ]

    def run(self, tool_id: str, args: list[str] | None, cwd: str | None, wait_seconds: float = 0.0) -> dict[str, Any]:
        entry = self._entry(tool_id)
        values = [str(value) for value in (args or [])]
        started = self.processes.start(
            kind="tool",
            executable_id=entry.id,
            argv=[entry.executable, *values],
            cwd=cwd,
            batch_wrapper=entry.batch_wrapper,
            audit_detail={"argumentCount": len(values)},
        )
        return self.processes.wait(started["processId"], wait_seconds)

    def status(self, process_id: str) -> dict[str, Any]:
        return self.processes.status(process_id)

    def cancel(self, process_id: str) -> dict[str, Any]:
        return self.processes.cancel(process_id)

    def _entry(self, tool_id: str) -> ExecutableEntry:
        entry = self._entries.get(str(tool_id or "").strip().lower())
        if entry is None:
            raise FileNotFoundError("local tool is not registered by Desktop Bridge")
        return entry


class AppCatalog:
    def __init__(self, settings: Settings, audit: AuditLogger | None = None):
        self.settings = settings
        self.policy = PathPolicy(settings.grants)
        self.audit = audit or AuditLogger(settings.audit_file)
        self._entries: dict[str, ExecutableEntry] = {}
        self._launched: dict[int, str] = {}
        self.refresh()

    def refresh(self) -> list[dict[str, Any]]:
        entries: dict[str, ExecutableEntry] = {}
        if self.settings.auto_discover_executables:
            for entry_id, (display_name, names) in KNOWN_APPS.items():
                found = _find_known(names, app=True)
                if found:
                    entries[entry_id] = ExecutableEntry(entry_id, display_name, found, "discovered")
        for entry in _configured_entries(self.settings.allowed_apps_json, "DESKTOP_ALLOWED_APPS_JSON"):
            entries[entry.id] = entry
        self._entries = entries
        self.audit.write("app.discover", ok=True, detail={"count": len(entries)})
        return self.list()

    def list(self) -> list[dict[str, Any]]:
        return [
            {"id": item.id, "displayName": item.display_name, "executable": item.executable, "source": item.source}
            for item in sorted(self._entries.values(), key=lambda value: value.id)
        ]

    def launch(self, app_id: str, args: list[str] | None = None) -> dict[str, Any]:
        entry = self._entry(app_id)
        values = [str(value) for value in (args or [])]
        if len(values) > 32 or any(len(value) > 2048 or "\x00" in value for value in values):
            raise ValueError("application arguments are invalid")
        proc = subprocess.Popen(
            [entry.executable, *values],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            env=safe_environment(),
        )
        self._launched[proc.pid] = entry.id
        self.audit.write("app.launch", ok=True, detail={"appId": entry.id, "pid": proc.pid, "argumentCount": len(values)})
        return {"appId": entry.id, "displayName": entry.display_name, "pid": proc.pid, "launched": True}

    def open(self, app_id: str, path: str) -> dict[str, Any]:
        target, _ = self.policy.resolve(path, "read")
        if not target.exists():
            raise FileNotFoundError("target file or folder does not exist")
        result = self.launch(app_id, [str(target)])
        result["path"] = str(target)
        return result

    def status(self, app_id: str | None = None) -> dict[str, Any]:
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError("psutil is required for application status") from exc
        wanted = str(app_id or "").strip().lower()
        names = {Path(item.executable).name.casefold(): item for item in self._entries.values() if not wanted or item.id == wanted}
        running = []
        for process in psutil.process_iter(["pid", "name", "exe"]):
            try:
                name = str(process.info.get("name") or Path(str(process.info.get("exe") or "")).name).casefold()
                entry = names.get(name)
                if entry:
                    running.append({"appId": entry.id, "displayName": entry.display_name, "pid": process.info["pid"]})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return {"running": running}

    def focus(self, app_id: str) -> dict[str, Any]:
        if os.name != "nt":
            raise RuntimeError("application focus is currently supported on Windows only")
        entry = self._entry(app_id)
        try:
            from pywinauto import Desktop
        except ImportError as exc:
            raise RuntimeError("pywinauto is required for Windows application focus") from exc
        exe_name = Path(entry.executable).name.casefold()
        for window in Desktop(backend="uia").windows():
            try:
                process = window.process_id()
                import psutil
                if psutil.Process(process).name().casefold() == exe_name:
                    window.set_focus()
                    self.audit.write("app.focus", ok=True, detail={"appId": entry.id, "pid": process})
                    return {"appId": entry.id, "focused": True, "pid": process, "title": window.window_text()[:240]}
            except Exception:
                continue
        raise FileNotFoundError("no visible window was found for the application")

    def close(self, app_id: str, pid: int | None = None) -> dict[str, Any]:
        entry = self._entry(app_id)
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError("psutil is required for application close") from exc

        # A close without an explicit PID is intentionally limited to process
        # instances launched by this Desktop Bridge. Merely sharing the same
        # executable name is not enough: otherwise a custom Python/Java app
        # entry could terminate unrelated user processes.
        if pid is None:
            candidates = [
                launched_pid
                for launched_pid, launched_app_id in self._launched.items()
                if launched_app_id == entry.id
            ]
        else:
            candidates = [int(pid)]

        matches: list[int] = []
        exe_name = Path(entry.executable).name.casefold()
        for candidate_pid in candidates:
            try:
                process = psutil.Process(candidate_pid)
                process_name = process.name().casefold()
                if process_name != exe_name:
                    # An OS PID may have been recycled after the process that
                    # Desktop Bridge launched exited. Fail closed in that case.
                    self._launched.pop(candidate_pid, None)
                    continue
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except psutil.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2.0)
                matches.append(candidate_pid)
                self._launched.pop(candidate_pid, None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self._launched.pop(candidate_pid, None)
                continue

        self.audit.write(
            "app.close",
            ok=True,
            detail={"appId": entry.id, "requestedPid": pid, "pids": matches[:20]},
        )
        return {"appId": entry.id, "closedPids": matches}

    def _entry(self, app_id: str) -> ExecutableEntry:
        entry = self._entries.get(str(app_id or "").strip().lower())
        if entry is None:
            raise FileNotFoundError("local application is not registered by Desktop Bridge")
        return entry
