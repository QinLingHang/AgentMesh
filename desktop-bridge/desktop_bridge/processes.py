from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .audit import AuditLogger
from .config import Settings
from .policy import DesktopPermissionError, PathPolicy


_SECRET_ENV_MARKERS = (
    "TOKEN", "SECRET", "PASSWORD", "PASSWD", "API_KEY", "APIKEY",
    "CREDENTIAL", "AUTHORIZATION", "COOKIE", "PRIVATE_KEY",
    "ACCESS_KEY", "CLIENT_SECRET", "SESSION_SECRET", "ENCRYPTION_KEY",
)
_BATCH_META = set("&|<>^%!\r\n")


def safe_environment() -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if key == "DESKTOP_BRIDGE_TOKEN" or any(marker in upper for marker in _SECRET_ENV_MARKERS):
            continue
        env[key] = value
    return env


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


@dataclass(slots=True)
class _ManagedProcess:
    process_id: str
    kind: str
    executable_id: str
    executable: str
    cwd: str
    process: subprocess.Popen[bytes]
    started_at: float
    max_output_bytes: int
    stdout: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def append(self, stream: str, chunk: bytes) -> None:
        target = self.stdout if stream == "stdout" else self.stderr
        with self.lock:
            remaining = self.max_output_bytes - len(target)
            if remaining > 0:
                target.extend(chunk[:remaining])
            if len(chunk) > max(0, remaining):
                if stream == "stdout":
                    self.stdout_truncated = True
                else:
                    self.stderr_truncated = True


class ProcessManager:
    def __init__(self, settings: Settings, audit: AuditLogger | None = None):
        self.settings = settings
        self.policy = PathPolicy(settings.grants)
        self.audit = audit or AuditLogger(settings.audit_file)
        self._processes: dict[str, _ManagedProcess] = {}
        self._lock = threading.Lock()

    def _cwd(self, value: str | None) -> Path:
        if value:
            target, _ = self.policy.resolve(value, "read")
            if not target.exists() or not target.is_dir():
                raise NotADirectoryError("working directory does not exist")
            return target
        if not self.settings.grants:
            raise DesktopPermissionError("at least one authorized root is required for local process execution")
        target, _ = self.policy.resolve(str(self.settings.grants[0].path), "read")
        return target

    def _reader(self, managed: _ManagedProcess, stream_name: str, pipe) -> None:
        try:
            while True:
                chunk = pipe.read(4096)
                if not chunk:
                    break
                managed.append(stream_name, chunk)
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def start(
        self,
        *,
        kind: str,
        executable_id: str,
        argv: list[str],
        cwd: str | None,
        batch_wrapper: bool = False,
        audit_detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workdir = self._cwd(cwd)
        if not argv:
            raise ValueError("process argv is required")
        if len(argv) > 65:
            raise ValueError("too many process arguments")
        for item in argv:
            if len(str(item)) > 2048 or "\x00" in str(item):
                raise ValueError("process argument is invalid or too long")

        command = list(argv)
        executable = command[0]
        if batch_wrapper:
            if os.name != "nt":
                raise ValueError("Windows batch wrappers are supported only on Windows")
            for value in command:
                if any(char in value for char in _BATCH_META):
                    raise ValueError("batch-wrapper arguments contain forbidden command metacharacters")
            cmd_exe = os.environ.get("COMSPEC") or shutil.which("cmd.exe") or "cmd.exe"
            command_line = subprocess.list2cmdline(command)
            command = [cmd_exe, "/d", "/s", "/c", command_line]
            executable = cmd_exe

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = subprocess.Popen(
            command,
            cwd=str(workdir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=safe_environment(),
            creationflags=creationflags,
        )
        pid = str(uuid.uuid4())
        managed = _ManagedProcess(
            process_id=pid,
            kind=kind,
            executable_id=executable_id,
            executable=executable,
            cwd=str(workdir),
            process=proc,
            started_at=time.time(),
            max_output_bytes=self.settings.process_output_max_bytes,
        )
        with self._lock:
            self._processes[pid] = managed

        assert proc.stdout is not None and proc.stderr is not None
        threading.Thread(target=self._reader, args=(managed, "stdout", proc.stdout), daemon=True).start()
        threading.Thread(target=self._reader, args=(managed, "stderr", proc.stderr), daemon=True).start()

        detail = {
            "processId": pid,
            "kind": kind,
            "executableId": executable_id,
            "cwd": str(workdir),
            "osPid": proc.pid,
        }
        detail.update(audit_detail or {})
        self.audit.write(f"{kind}.run", ok=True, detail=detail)
        return self.status(pid)

    def status(self, process_id: str) -> dict[str, Any]:
        managed = self._get(process_id)
        return_code = managed.process.poll()
        elapsed_ms = int((time.time() - managed.started_at) * 1000)
        with managed.lock:
            stdout = _decode(bytes(managed.stdout))
            stderr = _decode(bytes(managed.stderr))
            stdout_truncated = managed.stdout_truncated
            stderr_truncated = managed.stderr_truncated
        return {
            "processId": process_id,
            "kind": managed.kind,
            "executableId": managed.executable_id,
            "cwd": managed.cwd,
            "running": return_code is None,
            "exitCode": return_code,
            "elapsedMs": elapsed_ms,
            "stdout": stdout,
            "stderr": stderr,
            "stdoutTruncated": stdout_truncated,
            "stderrTruncated": stderr_truncated,
        }

    def wait(self, process_id: str, wait_seconds: float) -> dict[str, Any]:
        managed = self._get(process_id)
        timeout = max(0.0, min(float(wait_seconds), self.settings.process_initial_wait_seconds))
        if timeout > 0:
            try:
                managed.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
        return self.status(process_id)

    def cancel(self, process_id: str) -> dict[str, Any]:
        managed = self._get(process_id)
        if managed.process.poll() is None:
            managed.process.terminate()
            try:
                managed.process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                managed.process.kill()
                managed.process.wait(timeout=2.0)
        self.audit.write(
            f"{managed.kind}.cancel",
            ok=True,
            detail={"processId": process_id, "executableId": managed.executable_id},
        )
        result = self.status(process_id)
        result["cancelled"] = True
        return result

    def _get(self, process_id: str) -> _ManagedProcess:
        value = str(process_id or "").strip()
        with self._lock:
            managed = self._processes.get(value)
        if managed is None:
            raise FileNotFoundError("process was not found or no longer belongs to this bridge instance")
        return managed
