#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import json
from pathlib import Path

EXPECTED_VERSION = "1.0.0-rc.1"
FINAL_TARGET = "1.0.0"

DEFAULT_ROOT = Path(__file__).resolve().parents[2]

REQUIRED = [
    "VERSION",
    "MANIFEST.json",
    "README.md",
    "docs/p12/FINAL_RELEASE.md",
    "docs/p12/RELEASE_CHECKLIST.md",
    "docs/p12/FULL_MANUAL_ACCEPTANCE.md",
    "docs/p12/SECURITY_BOUNDARIES.md",
    "docs/p12/DEMO_SCRIPT.md",
    "docs/p12/INTERVIEW_GUIDE.md",
    "docs/p12/RESUME_PROJECT.md",
    "docs/p12/CODEX_P12_VALIDATION.md",
    "docs/p12/P12_CHANGE_MANIFEST.md",
    "docs/p12/P12_COMPLETION.md",
    "docs/p12/P12_DEV_VALIDATION.md",
    "docs/p12/P12_VALIDATION_CLOSURE_1.md",
    "docs/p12/P12_FINAL_FULL_ACCEPTANCE_CLOSURE_2.md",
    "scripts/release/stage-release.py",
    "scripts/release/package-release.ps1",
    "scripts/release/package-release.sh",
]

FORBIDDEN_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "__pycache__",
    ".pytest_cache",
    "backups",
    ".agentmesh-backups",
}
FORBIDDEN_DIR_PREFIXES = (".p11-browser-",)
BACKUP_DIR_PATTERN = re.compile(r"(^|[._-])backups?([._-]|$)", re.IGNORECASE)
FORBIDDEN_EXACT = {".env", ".env.production"}
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate AgentMesh P12 release identity and hygiene.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="tree to validate")
    parser.add_argument(
        "--strict-tree",
        action="store_true",
        help="fail if release-excluded local/generated/secret material exists; required for release staging/archive roots",
    )
    return parser.parse_args()


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read_json(root: Path, path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid JSON {path.relative_to(root)}: {exc}")


def check_version(root: Path) -> None:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    require(version == EXPECTED_VERSION, f"VERSION must be {EXPECTED_VERSION}, got {version!r}")

    manifest = read_json(root, root / "MANIFEST.json")
    require(manifest.get("version") == EXPECTED_VERSION, "MANIFEST.json version mismatch")
    release = manifest.get("release") or {}
    require(release.get("candidate") == EXPECTED_VERSION, "manifest release candidate mismatch")
    require(release.get("final_target") == FINAL_TARGET, "manifest final target mismatch")

    package = read_json(root, root / "web-react/package.json")
    lock = read_json(root, root / "web-react/package-lock.json")
    require(package.get("version") == EXPECTED_VERSION, "web-react/package.json version mismatch")
    require(lock.get("version") == EXPECTED_VERSION, "web-react/package-lock.json version mismatch")
    require((lock.get("packages") or {}).get("", {}).get("version") == EXPECTED_VERSION, "package-lock root package version mismatch")


def check_required(root: Path) -> None:
    for rel in REQUIRED:
        path = root / rel
        require(path.is_file(), f"missing required release artifact: {rel}")
        require(path.stat().st_size > 0, f"empty required release artifact: {rel}")


def check_readme(root: Path) -> None:
    text = (root / "README.md").read_text(encoding="utf-8")
    for needle in [
        "v1.0.0-rc.1",
        "docs/p12/FINAL_RELEASE.md",
        "docs/p12/FULL_MANUAL_ACCEPTANCE.md",
        "docs/p10/RUNBOOK.md",
        "docs/p11/P11_COMPLETION.md",
    ]:
        require(needle in text, f"README missing release entry: {needle}")


def tree_hygiene_findings(root: Path) -> list[str]:
    findings: list[str] = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in FORBIDDEN_DIRS for part in rel.parts):
            findings.append(str(rel))
            continue
        if any(part.startswith(FORBIDDEN_DIR_PREFIXES) for part in rel.parts):
            findings.append(str(rel))
            continue
        if any(BACKUP_DIR_PATTERN.search(part) for part in rel.parts):
            findings.append(str(rel))
            continue
        if path.is_file() or path.is_symlink():
            if path.name in FORBIDDEN_EXACT:
                findings.append(str(rel))
            elif path.suffix.lower() in FORBIDDEN_SUFFIXES:
                findings.append(str(rel))
    return findings


def check_tree_hygiene(root: Path, strict_tree: bool) -> None:
    findings = tree_hygiene_findings(root)
    if strict_tree:
        require(not findings, "forbidden generated/secret/backup material found: " + ", ".join(findings[:20]))
    elif findings:
        print(
            "[INFO] development-tree release exclusions detected; packaging will sanitize them "
            f"before strict validation: count={len(findings)} sample={', '.join(findings[:8])}"
        )


def check_manual_contract(root: Path) -> None:
    text = (root / "docs/p12/FULL_MANUAL_ACCEPTANCE.md").read_text(encoding="utf-8")
    require("FULL MANUAL ACCEPTANCE: PASS / FAIL" in text, "manual acceptance final verdict is missing")
    require("Only `FULL MANUAL ACCEPTANCE: PASS` permits promotion" in text, "manual acceptance promotion rule is missing")


def check_docs_no_false_release(root: Path) -> None:
    text = (root / "docs/p12/FINAL_RELEASE.md").read_text(encoding="utf-8")
    require("v1.0.0-rc.1" in text, "RC identity missing")
    require("v1.0.0" in text, "final target missing")
    require("FULL MANUAL ACCEPTANCE" in text, "manual promotion gate missing")


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    require(root.is_dir(), f"release root not found: {root}")
    check_required(root)
    check_version(root)
    check_readme(root)
    check_tree_hygiene(root, args.strict_tree)
    check_manual_contract(root)
    check_docs_no_false_release(root)
    print("P12 Release Validator: PASS")
    print(f"candidate={EXPECTED_VERSION} final_target={FINAL_TARGET} strict_tree={args.strict_tree}")


if __name__ == "__main__":
    main()
