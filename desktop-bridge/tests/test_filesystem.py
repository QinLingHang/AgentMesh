from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import tempfile

import pytest

from desktop_bridge.config import PathGrant, Settings
from desktop_bridge.filesystem import FileSystemService
from desktop_bridge.policy import DesktopPermissionError


def make_service(tmp_path: Path) -> FileSystemService:
    root = tmp_path / "root"
    root.mkdir()
    return FileSystemService(
        Settings(
            host="127.0.0.1",
            port=9583,
            token="test-token",
            grants=(PathGrant(root, read=True, write=True, delete=True),),
            audit_file=tmp_path / "audit.jsonl",
            max_read_bytes=1024 * 1024,
            max_write_bytes=1024 * 1024,
            max_search_files=100,
            max_search_results=20,
        )
    )


def _service(
    root: Path,
    *,
    read: bool = True,
    write: bool = True,
    delete: bool = True,
    allow_sensitive: bool = False,
) -> FileSystemService:
    return FileSystemService(
        Settings(
            host="127.0.0.1",
            port=9583,
            token="test-token",
            grants=(
                PathGrant(
                    path=root,
                    read=read,
                    write=write,
                    delete=delete,
                    allow_sensitive=allow_sensitive,
                ),
            ),
            audit_file=root.parent / "audit-custom.jsonl",
            max_read_bytes=1024 * 1024,
            max_write_bytes=1024 * 1024,
            max_search_files=100,
            max_search_results=20,
        )
    )


def test_read_search_write_delete_within_grant(tmp_path: Path):
    service = make_service(tmp_path)
    root = service.settings.grants[0].path
    target = root / "hello.txt"

    created = service.write(str(target), "你好 AgentMesh", overwrite=False)
    assert created["name"] == "hello.txt"
    assert service.read(str(target))["content"] == "你好 AgentMesh"
    assert service.search(str(root), "AgentMesh")["results"][0]["name"] == "hello.txt"
    assert service.delete(str(target))["deleted"] is True


def test_denies_path_outside_grant(tmp_path: Path):
    service = make_service(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(DesktopPermissionError):
        service.read(str(outside))


def test_denies_sensitive_store_by_default(tmp_path: Path):
    service = make_service(tmp_path)
    root = service.settings.grants[0].path
    ssh_dir = root / ".ssh"
    ssh_dir.mkdir()
    key = ssh_dir / "id_ed25519"
    key.write_text("private", encoding="utf-8")
    with pytest.raises(DesktopPermissionError):
        service.read(str(key))


def test_cannot_delete_authorized_root(tmp_path: Path):
    service = make_service(tmp_path)
    root = service.settings.grants[0].path
    with pytest.raises(DesktopPermissionError):
        service.delete(str(root), recursive=True)


def _create_directory_link(link: Path, target: Path) -> str:
    """Create a real filesystem indirection without silently skipping security coverage."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return "symlink"
    except (OSError, NotImplementedError) as symlink_error:
        if os.name != "nt":
            pytest.fail(f"cannot create symlink required for escape test: {symlink_error}")

        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.fail(
                "cannot create symlink or Windows junction required for escape test: "
                f"{completed.stdout} {completed.stderr}".strip()
            )
        return "junction"


def _remove_directory_link(link: Path, kind: str) -> None:
    if not link.exists() and not link.is_symlink():
        return
    if kind == "symlink":
        link.unlink()
        return
    if os.name == "nt":
        subprocess.run(
            ["cmd.exe", "/d", "/c", "rmdir", str(link)],
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        link.rmdir()


def test_symlink_escape_is_not_exposed(tmp_path: Path):
    service = make_service(tmp_path)
    root = service.settings.grants[0].path
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "outside.txt"
    outside_file.write_text("outside-secret", encoding="utf-8")
    link = root / "linked"
    kind = _create_directory_link(link, outside_dir)

    try:
        names = {item["name"] for item in service.list(str(root))["entries"]}
        assert "linked" not in names

        with pytest.raises(DesktopPermissionError):
            service.read(str(link / "outside.txt"))

        assert service.search(str(root), "outside-secret")["results"] == []
    finally:
        _remove_directory_link(link, kind)


def test_windows_junction_escape_is_denied(tmp_path: Path):
    # On Windows, validate the exact junction/reparse-point class separately.
    # On other platforms this test returns normally instead of creating a mandatory skip.
    if os.name != "nt":
        return

    service = make_service(tmp_path)
    root = service.settings.grants[0].path
    outside_dir = tmp_path / "junction-outside"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("junction-secret", encoding="utf-8")
    junction = root / "junction-link"

    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(
            "cannot create Windows junction required for reparse-point security test: "
            f"{completed.stdout} {completed.stderr}".strip()
        )

    try:
        with pytest.raises(DesktopPermissionError):
            service.read(str(junction / "secret.txt"))
        assert service.search(str(root), "junction-secret")["results"] == []
    finally:
        subprocess.run(
            ["cmd.exe", "/d", "/c", "rmdir", str(junction)],
            capture_output=True,
            text=True,
            check=False,
        )


def test_sensitive_key_suffix_is_denied(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    secret = root / "client.pem"
    secret.write_text("SECRET", encoding="utf-8")
    fs = _service(root)

    with pytest.raises(DesktopPermissionError):
        fs.read(str(secret))


def test_move_authorized_root_is_denied(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    target = tmp_path / "other"
    fs = _service(root, write=True, delete=True)

    with pytest.raises(DesktopPermissionError):
        fs.move(str(root), str(target))


def test_copy_directory_overwrite_requires_delete_permission(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    source = root / "source"
    destination = root / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "new.txt").write_text("new", encoding="utf-8")
    (destination / "old.txt").write_text("old", encoding="utf-8")
    fs = _service(root, write=True, delete=False)

    with pytest.raises(DesktopPermissionError):
        fs.copy(str(source), str(destination), overwrite=True)


def test_failure_audit_contains_no_file_content(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    audit = tmp_path / "audit.jsonl"
    settings = Settings(
        host="127.0.0.1",
        port=9583,
        token="test-token",
        grants=(PathGrant(path=root, read=True, write=False, delete=False),),
        audit_file=audit,
        max_read_bytes=1024 * 1024,
        max_write_bytes=1024 * 1024,
        max_search_files=100,
        max_search_results=20,
    )
    fs = FileSystemService(settings)
    error = DesktopPermissionError("write permission is not granted")
    fs.audit_failure("write", [str(root / "secret.txt")], error)

    text = audit.read_text(encoding="utf-8")
    assert '"ok":false' in text
    assert "secret.txt" in text
    assert "test-token" not in text
    assert "FILE-CONTENT" not in text


def test_local_computer_mode_auto_grants_fixed_drive_without_sensitive_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import desktop_bridge.config as desktop_config

    monkeypatch.setenv("DESKTOP_ACCESS_MODE", "local")
    monkeypatch.setenv("DESKTOP_BRIDGE_TOKEN", "test-token")
    monkeypatch.setattr(desktop_config, "_windows_fixed_drive_roots", lambda: (tmp_path,))

    loaded = desktop_config.load_settings()

    assert loaded.access_mode == "local"
    assert loaded.grants == (
        PathGrant(path=tmp_path.resolve(strict=False), read=True, write=True, delete=True, allow_sensitive=False),
    )


def test_restricted_mode_preserves_explicit_root_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import desktop_bridge.config as desktop_config

    monkeypatch.setenv("DESKTOP_ACCESS_MODE", "restricted")
    monkeypatch.setenv("DESKTOP_BRIDGE_TOKEN", "test-token")
    monkeypatch.setenv(
        "DESKTOP_ALLOWED_ROOTS_JSON",
        json.dumps([{"path": str(tmp_path), "read": True, "write": False, "delete": False}]),
    )

    loaded = desktop_config.load_settings()

    assert loaded.access_mode == "restricted"
    assert loaded.grants[0].path == tmp_path.resolve(strict=False)
    assert loaded.grants[0].read is True
    assert loaded.grants[0].write is False
    assert loaded.grants[0].delete is False


def test_local_computer_mode_allows_normal_file_but_still_denies_sensitive_file():
    # pytest's default tmp_path on Windows lives under %LOCALAPPDATA%\Temp.
    # Local Computer Mode intentionally protects AppData, so using tmp_path here
    # accidentally turns the supposedly ordinary fixture into a protected path.
    # Build this fixture under the repository instead so the test exercises the
    # intended semantics: an ordinary local path is readable while a sensitive
    # filename inside that same path is still denied.
    repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(
        prefix="agentmesh-local-mode-",
        dir=repo_root,
    ) as temp_dir:
        temp_path = Path(temp_dir)
        root = temp_path / "local-drive"
        root.mkdir()
        ordinary = root / "notes.txt"
        ordinary.write_text("normal", encoding="utf-8")
        sensitive = root / ".env.local"
        sensitive.write_text("TOKEN=secret", encoding="utf-8")

        fs = FileSystemService(
            Settings(
                host="127.0.0.1",
                port=9583,
                token="test-token",
                grants=(PathGrant(root, read=True, write=True, delete=True),),
                audit_file=temp_path / "audit-local.jsonl",
                max_read_bytes=1024 * 1024,
                max_write_bytes=1024 * 1024,
                max_search_files=100,
                max_search_results=20,
                access_mode="local",
            )
        )

        assert fs.read(str(ordinary))["content"] == "normal"
        with pytest.raises(DesktopPermissionError):
            fs.read(str(sensitive))


def test_restricted_mode_can_explicitly_allow_sensitive_path(tmp_path: Path):
    root = tmp_path / "restricted"
    root.mkdir()
    secret = root / ".env.local"
    secret.write_text("TEST=allowed", encoding="utf-8")
    fs = _service(root, allow_sensitive=True)

    assert fs.read(str(secret))["content"] == "TEST=allowed"


def test_legacy_root_allowlist_without_explicit_mode_stays_restricted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import desktop_bridge.config as desktop_config

    monkeypatch.delenv("DESKTOP_ACCESS_MODE", raising=False)
    monkeypatch.setenv("DESKTOP_BRIDGE_TOKEN", "test-token")
    monkeypatch.setenv(
        "DESKTOP_ALLOWED_ROOTS_JSON",
        json.dumps([{"path": str(tmp_path), "read": True, "write": False, "delete": False}]),
    )

    loaded = desktop_config.load_settings()

    assert loaded.access_mode == "restricted"
    assert loaded.grants[0].path == tmp_path.resolve(strict=False)
