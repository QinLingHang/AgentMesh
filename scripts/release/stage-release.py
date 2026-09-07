#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

FORBIDDEN_DIR_NAMES = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "__pycache__",
    ".pytest_cache",
    "backups",
    ".agentmesh-backups",
}
FORBIDDEN_EXACT_FILES = {".env", ".env.production"}
FORBIDDEN_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".bak",
    ".orig",
    ".swp",
    ".tmp",
    ".log",
    ".zip",
}
FORBIDDEN_DIR_PREFIXES = (".p11-browser-",)
BACKUP_DIR_PATTERN = re.compile(r"(^|[._-])backups?([._-]|$)", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a sanitized AgentMesh release staging tree.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--dest", required=True, type=Path)
    return parser.parse_args()


def excluded(path: Path, source: Path) -> bool:
    rel = path.relative_to(source)
    if any(part in FORBIDDEN_DIR_NAMES for part in rel.parts):
        return True
    if any(part.startswith(FORBIDDEN_DIR_PREFIXES) for part in rel.parts):
        return True
    if any(BACKUP_DIR_PATTERN.search(part) for part in rel.parts):
        return True
    if path.is_file() or path.is_symlink():
        if path.name in FORBIDDEN_EXACT_FILES:
            return True
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            return True
    return False


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    dest = args.dest.resolve()

    if not source.is_dir():
        raise SystemExit(f"source does not exist or is not a directory: {source}")
    if source == dest or source in dest.parents:
        # dest below source would recursively copy itself and contaminate the source tree.
        raise SystemExit("destination must be outside the source tree")

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    copied_files = 0
    excluded_items = 0

    for path in sorted(source.rglob("*")):
        if excluded(path, source):
            excluded_items += 1
            continue
        rel = path.relative_to(source)
        target = dest / rel
        if path.is_symlink():
            # Release source archives should be self-contained and must not preserve links
            # that can resolve outside the package on another machine.
            excluded_items += 1
            continue
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied_files += 1

    print("P12 Release Staging: PASS")
    print(f"source={source}")
    print(f"dest={dest}")
    print(f"copied_files={copied_files} excluded_items={excluded_items}")


if __name__ == "__main__":
    main()
