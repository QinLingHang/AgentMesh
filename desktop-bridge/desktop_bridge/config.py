from __future__ import annotations

import ctypes
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BRIDGE_ROOT = Path(__file__).resolve().parents[1]


def _load_local_env() -> None:
    """Load bridge-local developer defaults without overriding real environment vars."""
    explicit = str(os.getenv("DESKTOP_ENV_FILE") or "").strip()
    candidates = [Path(explicit)] if explicit else [BRIDGE_ROOT / ".env.local", BRIDGE_ROOT / ".env"]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        for raw_line in candidate.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ.setdefault(key, value)
        return


_load_local_env()


@dataclass(frozen=True, slots=True)
class PathGrant:
    path: Path
    read: bool = True
    write: bool = False
    delete: bool = False
    allow_sensitive: bool = False


@dataclass(frozen=True, slots=True)
class Settings:
    host: str
    port: int
    token: str
    grants: tuple[PathGrant, ...]
    audit_file: Path
    max_read_bytes: int
    max_write_bytes: int
    max_search_files: int
    max_search_results: int
    access_mode: str = "restricted"
    default_working_directory: Path | None = None
    auto_discover_executables: bool = True
    allowed_apps_json: str = "[]"
    allowed_tools_json: str = "[]"
    allow_terminal: bool = False
    computer_use_enabled: bool = False
    computer_session_ttl_seconds: int = 1800
    process_output_max_bytes: int = 262_144
    process_initial_wait_seconds: float = 30.0
    screenshot_max_width: int = 1920
    screenshot_max_bytes: int = 5_242_880


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _restricted_grants() -> tuple[PathGrant, ...]:
    raw = os.getenv("DESKTOP_ALLOWED_ROOTS_JSON", "[]").strip() or "[]"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("DESKTOP_ALLOWED_ROOTS_JSON must be valid JSON") from exc

    if not isinstance(payload, list):
        raise RuntimeError("DESKTOP_ALLOWED_ROOTS_JSON must be a JSON array")

    grants: list[PathGrant] = []
    for index, item in enumerate(payload):
        if isinstance(item, str):
            item = {"path": item, "read": True}
        if not isinstance(item, dict):
            raise RuntimeError(f"desktop root #{index + 1} must be an object or string")
        value = str(item.get("path") or "").strip()
        if not value:
            raise RuntimeError(f"desktop root #{index + 1} path is required")
        root = Path(value).expanduser().resolve(strict=False)
        grants.append(
            PathGrant(
                path=root,
                read=_bool(item.get("read"), True),
                write=_bool(item.get("write"), False),
                delete=_bool(item.get("delete"), False),
                allow_sensitive=_bool(item.get("allowSensitive"), False),
            )
        )
    return tuple(grants)


def _windows_fixed_drive_roots() -> tuple[Path, ...]:
    if os.name != "nt":
        return ()
    roots: list[Path] = []
    try:
        get_logical_drives = ctypes.windll.kernel32.GetLogicalDrives
        get_logical_drives.restype = ctypes.c_uint
        get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
        get_drive_type.argtypes = [ctypes.c_wchar_p]
        get_drive_type.restype = ctypes.c_uint
        bitmask = int(get_logical_drives())
        for index in range(26):
            if not bitmask & (1 << index):
                continue
            root = f"{chr(ord('A') + index)}:\\"
            # DRIVE_FIXED == 3. Network/removable/CD-ROM drives are intentionally
            # excluded from Local Computer Mode unless the user switches to a
            # restricted explicit grant.
            if int(get_drive_type(root)) == 3:
                roots.append(Path(root).resolve(strict=False))
    except Exception:
        return ()
    return tuple(roots)


def _local_computer_grants() -> tuple[PathGrant, ...]:
    roots = list(_windows_fixed_drive_roots())
    if not roots:
        home = Path.home().expanduser().resolve(strict=False)
        anchor = Path(home.anchor).resolve(strict=False) if home.anchor else home
        roots = [anchor]
    return tuple(
        PathGrant(
            path=root,
            read=True,
            # Mutation capability is present, but the Runtime tool contracts still
            # require explicit approval for write/copy/move/delete operations.
            write=True,
            delete=True,
            allow_sensitive=False,
        )
        for root in roots
    )


def _load_access() -> tuple[str, tuple[PathGrant, ...]]:
    explicit_mode = str(os.getenv("DESKTOP_ACCESS_MODE", "") or "").strip().lower()
    legacy_roots = str(os.getenv("DESKTOP_ALLOWED_ROOTS_JSON", "") or "").strip()

    # Backward compatibility: existing V4.1/enterprise launchers that provide an
    # explicit root allowlist but predate DESKTOP_ACCESS_MODE stay restricted.
    # With neither setting present, the product default is Local Computer Mode.
    if explicit_mode:
        mode = explicit_mode
    elif legacy_roots and legacy_roots not in {"[]", "null"}:
        mode = "restricted"
    else:
        mode = "local"

    if mode not in {"local", "restricted"}:
        raise RuntimeError("DESKTOP_ACCESS_MODE must be local or restricted")
    if mode == "local":
        grants = _local_computer_grants()
        if not grants:
            raise RuntimeError("Local Computer Mode could not discover an accessible local root")
        return mode, grants

    grants = _restricted_grants()
    if not grants:
        raise RuntimeError("Restricted Desktop mode requires DESKTOP_ALLOWED_ROOTS_JSON")
    return mode, grants


def load_settings() -> Settings:
    host = os.getenv("DESKTOP_BRIDGE_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Desktop Bridge must bind to loopback only")

    access_mode, grants = _load_access()
    default_working_directory = Path.home().expanduser().resolve(strict=False)

    return Settings(
        host=host,
        port=int(os.getenv("DESKTOP_BRIDGE_PORT", "9583")),
        token=os.getenv("DESKTOP_BRIDGE_TOKEN", "").strip(),
        grants=grants,
        audit_file=Path(os.getenv("DESKTOP_AUDIT_FILE", str(BRIDGE_ROOT / "data" / "desktop-audit.jsonl"))),
        max_read_bytes=max(1, int(os.getenv("DESKTOP_MAX_READ_BYTES", str(1_048_576)))),
        max_write_bytes=max(1, int(os.getenv("DESKTOP_MAX_WRITE_BYTES", str(2_097_152)))),
        max_search_files=max(1, int(os.getenv("DESKTOP_MAX_SEARCH_FILES", "2000"))),
        max_search_results=max(1, int(os.getenv("DESKTOP_MAX_SEARCH_RESULTS", "100"))),
        access_mode=access_mode,
        default_working_directory=default_working_directory,
        auto_discover_executables=_bool(os.getenv("DESKTOP_AUTO_DISCOVER_EXECUTABLES"), True),
        allowed_apps_json=os.getenv("DESKTOP_ALLOWED_APPS_JSON", "[]").strip() or "[]",
        allowed_tools_json=os.getenv("DESKTOP_ALLOWED_TOOLS_JSON", "[]").strip() or "[]",
        allow_terminal=_bool(os.getenv("DESKTOP_ALLOW_TERMINAL"), False),
        computer_use_enabled=_bool(os.getenv("DESKTOP_COMPUTER_USE_ENABLED"), False),
        computer_session_ttl_seconds=max(60, int(os.getenv("DESKTOP_COMPUTER_SESSION_TTL_SECONDS", "1800"))),
        process_output_max_bytes=max(16_384, int(os.getenv("DESKTOP_PROCESS_OUTPUT_MAX_BYTES", "262144"))),
        process_initial_wait_seconds=max(0.0, min(60.0, float(os.getenv("DESKTOP_PROCESS_INITIAL_WAIT_SECONDS", "30")))),
        screenshot_max_width=max(320, int(os.getenv("DESKTOP_SCREENSHOT_MAX_WIDTH", "1920"))),
        screenshot_max_bytes=max(262_144, int(os.getenv("DESKTOP_SCREENSHOT_MAX_BYTES", "5242880"))),
    )


settings = load_settings()
