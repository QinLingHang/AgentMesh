from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _service_block(compose: str, name: str, next_name: str | None) -> str:
    start = compose.index(f"  {name}:\n")
    if next_name is None:
        return compose[start:]
    end = compose.index(f"  {next_name}:\n", start + 1)
    return compose[start:end]


def test_production_topology_has_single_public_gateway():
    compose = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")

    backend = _service_block(compose, "backend-go", "runtime-python")
    runtime = _service_block(compose, "runtime-python", "mcp-demo")
    mcp = _service_block(compose, "mcp-demo", "web-react")
    web = _service_block(compose, "web-react", "gateway")
    gateway = _service_block(compose, "gateway", None)

    assert "    ports:\n" not in backend
    assert "    ports:\n" not in runtime
    assert "    ports:\n" not in mcp
    assert "    ports:\n" not in web
    assert '"${HTTP_PORT:-8080}:80"' in gateway
    assert '"${HTTPS_PORT:-8443}:443"' in gateway


def test_migration_and_secret_wiring_are_production_contracts():
    compose = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "backend-go" / "Dockerfile").read_text(encoding="utf-8")

    migrate = _service_block(compose, "migrate", "backend-go")
    backend = _service_block(compose, "backend-go", "runtime-python")

    assert 'command: ["/app/agentmesh-migrate"]' in migrate
    assert 'name: ${DATA_VOLUME_PREFIX:-agentmesh-prod}-mysql-data' in compose
    assert "condition: service_completed_successfully" in backend
    assert "GOVERNANCE_MASTER_KEY: ${GOVERNANCE_MASTER_KEY:?set GOVERNANCE_MASTER_KEY}" in compose
    assert "MINIO_ACCESS_KEY_ID:" in compose
    assert "MINIO_SECRET_ACCESS_KEY:" in compose
    assert "./cmd/migrate" in dockerfile
    assert 'CMD ["/app/agentmesh-control-plane"]' in dockerfile


def test_gateway_supports_same_origin_api_and_optional_tls():
    http_conf = (ROOT / "infra" / "gateway" / "http.conf").read_text(encoding="utf-8")
    https_conf = (ROOT / "infra" / "gateway" / "https.conf").read_text(encoding="utf-8")
    selector = (ROOT / "infra" / "gateway" / "10-select-agentmesh-config.sh").read_text(encoding="utf-8")
    web_dockerfile = (ROOT / "web-react" / "Dockerfile").read_text(encoding="utf-8")

    assert "location /api/" in http_conf
    assert "proxy_pass http://backend-go:8086;" in http_conf
    assert "proxy_pass http://web-react:80;" in http_conf
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in https_conf
    assert "Strict-Transport-Security" in https_conf
    assert 'REQUIRE_TLS="${REQUIRE_TLS:-false}"' in selector
    assert 'ARG VITE_API_BASE_URL=""' in web_dockerfile


def test_operations_scripts_and_backup_boundary_exist():
    ops = ROOT / "scripts" / "ops"
    required = [
        "init-production-env.ps1",
        "validate-production.ps1",
        "deploy-production.ps1",
        "smoke-production.ps1",
        "backup-production.ps1",
        "restore-production.ps1",
        "init-production-env.sh",
        "validate-production.sh",
        "deploy-production.sh",
        "smoke-production.sh",
        "backup-production.sh",
        "restore-production.sh",
    ]
    for name in required:
        assert (ops / name).is_file(), name

    ps_backup = (ops / "backup-production.ps1").read_text(encoding="utf-8")
    sh_backup = (ops / "backup-production.sh").read_text(encoding="utf-8")
    assert "Secrets (.env.production) and TLS private keys are intentionally excluded" in ps_backup
    assert "secretsAndTlsExcluded" in sh_backup
