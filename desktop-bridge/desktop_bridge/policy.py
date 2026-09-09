from __future__ import annotations

import os
from pathlib import Path

from .config import PathGrant


SENSITIVE_PARTS = {
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".kube",
    ".docker",
    "credentials",
}

SENSITIVE_FILES = {
    ".env",
    ".env.local",
    ".netrc",
    "_netrc",
    ".npmrc",
    ".pypirc",
    ".git-credentials",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "known_hosts",
}

SENSITIVE_SUFFIXES = {
    ".key",
    ".pem",
    ".p12",
    ".pfx",
}


class DesktopPermissionError(PermissionError):
    pass


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _contains(root: Path, target: Path) -> bool:
    root_value = _norm(root)
    target_value = _norm(target)
    try:
        return os.path.commonpath([root_value, target_value]) == root_value
    except ValueError:
        return False


class PathPolicy:
    def __init__(self, grants: tuple[PathGrant, ...]):
        self.grants = grants

    def _grant_for(self, target: Path, permission: str) -> PathGrant:
        candidates = [grant for grant in self.grants if _contains(grant.path, target)]
        candidates.sort(key=lambda item: len(_norm(item.path)), reverse=True)
        if not candidates:
            raise DesktopPermissionError("path is outside authorized roots")

        grant = candidates[0]
        allowed = {
            "read": grant.read,
            "write": grant.write,
            "delete": grant.delete,
        }.get(permission, False)
        if not allowed:
            raise DesktopPermissionError(f"{permission} permission is not granted for this path")
        return grant

    @staticmethod
    def _is_sensitive(target: Path) -> bool:
        parts = {part.casefold() for part in target.parts}
        name = target.name.casefold()
        suffix = target.suffix.casefold()
        return bool(
            parts & SENSITIVE_PARTS
            or name in SENSITIVE_FILES
            or suffix in SENSITIVE_SUFFIXES
        )

    def resolve(self, value: str, permission: str) -> tuple[Path, PathGrant]:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("path is required")

        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise ValueError("desktop file paths must be absolute")

        # resolve(strict=False) follows every existing parent symlink/junction.
        # Therefore a path that lexically appears under an allowed root but escapes
        # through a symlink is checked against its canonical target and denied.
        target = candidate.resolve(strict=False)
        grant = self._grant_for(target, permission)

        if not grant.allow_sensitive and self._is_sensitive(target):
            raise DesktopPermissionError(
                "sensitive path requires explicit allowSensitive permission"
            )

        return target, grant

    @staticmethod
    def is_grant_root(target: Path, grant: PathGrant) -> bool:
        return _norm(target) == _norm(grant.path)
