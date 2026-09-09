from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


def _load_grants() -> tuple[PathGrant, ...]:
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


def load_settings() -> Settings:
    host = os.getenv("DESKTOP_BRIDGE_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Desktop Bridge must bind to loopback only")

    return Settings(
        host=host,
        port=int(os.getenv("DESKTOP_BRIDGE_PORT", "9583")),
        token=os.getenv("DESKTOP_BRIDGE_TOKEN", "").strip(),
        grants=_load_grants(),
        audit_file=Path(os.getenv("DESKTOP_AUDIT_FILE", "./data/desktop-audit.jsonl")),
        max_read_bytes=max(1, int(os.getenv("DESKTOP_MAX_READ_BYTES", str(1_048_576)))),
        max_write_bytes=max(1, int(os.getenv("DESKTOP_MAX_WRITE_BYTES", str(2_097_152)))),
        max_search_files=max(1, int(os.getenv("DESKTOP_MAX_SEARCH_FILES", "2000"))),
        max_search_results=max(1, int(os.getenv("DESKTOP_MAX_SEARCH_RESULTS", "100"))),
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
