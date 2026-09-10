from __future__ import annotations

import fnmatch
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .policy import DesktopPermissionError, PathPolicy


class FileSystemService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.policy = PathPolicy(settings.grants, settings.access_mode)

    def _audit(self, operation: str, *, paths: list[Path], ok: bool, detail: dict[str, Any] | None = None) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "paths": [str(path) for path in paths],
            "ok": ok,
            "detail": detail or {},
        }
        path = self.settings.audit_file
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def audit_failure(self, operation: str, paths: list[str], error: Exception) -> None:
        # Failure auditing deliberately records only operation/path/error type.
        # File contents, bridge credentials, and request headers are never logged.
        safe_paths = [Path(str(value or "<empty>")) for value in paths]
        self._audit(
            operation,
            paths=safe_paths,
            ok=False,
            detail={"errorType": type(error).__name__, "message": str(error)[:240]},
        )

    @staticmethod
    def _metadata(path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "path": str(path),
            "name": path.name,
            "kind": "directory" if path.is_dir() else "file",
            "sizeBytes": stat.st_size if path.is_file() else 0,
            "modifiedAt": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }

    def list(self, path: str, limit: int = 500) -> dict[str, Any]:
        target, _ = self.policy.resolve(path, "read")
        if not target.exists():
            raise FileNotFoundError("path does not exist")
        if not target.is_dir():
            raise NotADirectoryError("path is not a directory")
        items = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
        visible: list[Path] = []
        for item in items:
            try:
                resolved, _ = self.policy.resolve(str(item), "read")
            except (DesktopPermissionError, ValueError):
                continue
            visible.append(resolved)
        capped = visible[: max(1, min(int(limit or 500), 500))]
        result = {"path": str(target), "entries": [self._metadata(item) for item in capped], "truncated": len(visible) > len(capped)}
        self._audit("list", paths=[target], ok=True, detail={"count": len(capped)})
        return result

    def stat(self, path: str) -> dict[str, Any]:
        target, _ = self.policy.resolve(path, "read")
        if not target.exists():
            raise FileNotFoundError("path does not exist")
        result = self._metadata(target)
        self._audit("stat", paths=[target], ok=True)
        return result

    @staticmethod
    def _decode_text(data: bytes) -> tuple[str, str]:
        if b"\x00" in data:
            raise ValueError("binary files are not supported by local.fs.read")
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return data.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        raise ValueError("file is not supported text encoding")

    def read(self, path: str, max_bytes: int | None = None) -> dict[str, Any]:
        target, _ = self.policy.resolve(path, "read")
        if not target.exists():
            raise FileNotFoundError("file does not exist")
        if not target.is_file():
            raise IsADirectoryError("path is not a file")
        limit = min(max(1, int(max_bytes or self.settings.max_read_bytes)), self.settings.max_read_bytes)
        size = target.stat().st_size
        if size > limit:
            raise ValueError(f"file exceeds read limit of {limit} bytes")
        data = target.read_bytes()
        text, encoding = self._decode_text(data)
        self._audit("read", paths=[target], ok=True, detail={"sizeBytes": size})
        return {"path": str(target), "content": text, "encoding": encoding, "sizeBytes": size}

    def search(
        self,
        path: str,
        query: str = "",
        name_pattern: str = "*",
        recursive: bool = True,
        max_results: int | None = None,
    ) -> dict[str, Any]:
        root, _ = self.policy.resolve(path, "read")
        if not root.exists() or not root.is_dir():
            raise NotADirectoryError("search root is not a directory")
        wanted = str(query or "").casefold()
        pattern = str(name_pattern or "*")
        limit = min(max(1, int(max_results or self.settings.max_search_results)), self.settings.max_search_results)
        iterator = root.rglob("*") if recursive else root.glob("*")
        results: list[dict[str, Any]] = []
        scanned = 0
        for item in iterator:
            if scanned >= self.settings.max_search_files or len(results) >= limit:
                break
            try:
                item, _ = self.policy.resolve(str(item), "read")
            except (DesktopPermissionError, ValueError):
                continue
            if not item.is_file():
                continue
            scanned += 1
            if not fnmatch.fnmatch(item.name.casefold(), pattern.casefold()):
                continue
            matched = not wanted or wanted in item.name.casefold()
            preview = ""
            if wanted and not matched:
                try:
                    if item.stat().st_size <= min(self.settings.max_read_bytes, 262_144):
                        text, _ = self._decode_text(item.read_bytes())
                        position = text.casefold().find(wanted)
                        if position >= 0:
                            matched = True
                            start = max(0, position - 80)
                            preview = text[start : position + len(query) + 160].replace("\r", " ").replace("\n", " ")
                except (OSError, ValueError, UnicodeError):
                    pass
            if matched:
                item_data = self._metadata(item)
                if preview:
                    item_data["preview"] = preview
                results.append(item_data)
        self._audit("search", paths=[root], ok=True, detail={"query": query[:120], "scanned": scanned, "results": len(results)})
        return {"path": str(root), "results": results, "scannedFiles": scanned, "truncated": scanned >= self.settings.max_search_files or len(results) >= limit}

    def write(self, path: str, content: str, overwrite: bool = False, create_parents: bool = False) -> dict[str, Any]:
        target, _ = self.policy.resolve(path, "write")
        encoded = str(content).encode("utf-8")
        if len(encoded) > self.settings.max_write_bytes:
            raise ValueError(f"content exceeds write limit of {self.settings.max_write_bytes} bytes")
        if target.exists() and target.is_dir():
            raise IsADirectoryError("path is a directory")
        if target.exists() and not overwrite:
            raise FileExistsError("file already exists; set overwrite=true to replace it")
        if not target.parent.exists():
            if not create_parents:
                raise FileNotFoundError("parent directory does not exist")
            parent, _ = self.policy.resolve(str(target.parent), "write")
            parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".agentmesh-", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        self._audit("write", paths=[target], ok=True, detail={"sizeBytes": len(encoded), "overwrite": overwrite})
        return self._metadata(target)

    def mkdir(self, path: str, parents: bool = True) -> dict[str, Any]:
        target, _ = self.policy.resolve(path, "write")
        target.mkdir(parents=bool(parents), exist_ok=True)
        self._audit("mkdir", paths=[target], ok=True)
        return self._metadata(target)

    def copy(self, source: str, destination: str, overwrite: bool = False) -> dict[str, Any]:
        src, _ = self.policy.resolve(source, "read")
        dst, _ = self.policy.resolve(destination, "write")
        if not src.exists():
            raise FileNotFoundError("source does not exist")
        if dst.exists() and not overwrite:
            raise FileExistsError("destination already exists")
        if src.is_dir():
            if dst.exists() and overwrite:
                # Replacing a directory recursively deletes its previous contents.
                # A write grant alone is intentionally insufficient for that.
                self.policy.resolve(str(dst), "delete")
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        self._audit("copy", paths=[src, dst], ok=True, detail={"overwrite": overwrite})
        return self._metadata(dst)

    def move(self, source: str, destination: str, overwrite: bool = False) -> dict[str, Any]:
        src, src_grant = self.policy.resolve(source, "delete")
        dst, _ = self.policy.resolve(destination, "write")
        if not src.exists():
            raise FileNotFoundError("source does not exist")
        if self.policy.is_grant_root(src, src_grant):
            raise DesktopPermissionError("authorized root itself cannot be moved")
        if dst.exists():
            if not overwrite:
                raise FileExistsError("destination already exists")
            # Overwriting an existing destination is destructive and requires
            # destination delete permission in addition to write permission.
            self.policy.resolve(str(dst), "delete")
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        self._audit("move", paths=[src, dst], ok=True, detail={"overwrite": overwrite})
        return self._metadata(dst)

    def delete(self, path: str, recursive: bool = False) -> dict[str, Any]:
        target, grant = self.policy.resolve(path, "delete")
        if not target.exists():
            raise FileNotFoundError("path does not exist")
        if self.policy.is_grant_root(target, grant):
            raise DesktopPermissionError("authorized root itself cannot be deleted")
        kind = "directory" if target.is_dir() else "file"
        if target.is_dir():
            if not recursive:
                target.rmdir()
            else:
                shutil.rmtree(target)
        else:
            target.unlink()
        self._audit("delete", paths=[target], ok=True, detail={"kind": kind, "recursive": recursive})
        return {"path": str(target), "deleted": True, "kind": kind}
