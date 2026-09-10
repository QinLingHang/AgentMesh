from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    """Metadata-only desktop audit logger.

    Callers must pass already-bounded metadata. Raw screen pixels, file contents,
    bridge tokens, terminal commands, and credentials are intentionally excluded.
    """

    def __init__(self, path: Path):
        self.path = path

    def write(self, operation: str, *, ok: bool, detail: dict[str, Any] | None = None) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "ok": bool(ok),
            "detail": detail or {},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def failure(self, operation: str, error: Exception, **detail: Any) -> None:
        payload = dict(detail)
        payload.update({"errorType": type(error).__name__, "message": str(error)[:240]})
        self.write(operation, ok=False, detail=payload)

    @staticmethod
    def digest_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
