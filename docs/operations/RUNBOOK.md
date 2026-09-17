# Production Runbook

## 1. Prerequisites

- Docker Desktop / Docker Engine with Compose v2.
- Windows PowerShell 5.1+ or PowerShell 7, or a Linux POSIX shell.
- For TLS mode: a directory containing `fullchain.pem` and `privkey.pem`.

## 2. Create production environment

Windows:

```powershell
cd "<agentmesh-root>"
.\scripts\ops\init-production-env.ps1
```

Linux:

```bash
./scripts/ops/init-production-env.sh
```

The generated `.env.production` contains independent random MySQL, MinIO, JWT,
verification, Runtime-internal, and Governance keys. Review it before real
Internet deployment.

For a real HTTPS deployment set at least:

```text
PUBLIC_ORIGIN=https://agentmesh.example.com
HTTP_PORT=80
HTTPS_PORT=443
REQUIRE_TLS=true
TLS_CERT_DIR=/secure/path/to/certs
AUTH_COOKIE_SECURE=true
EMAIL_PROVIDER=<real SMTP provider>
```

`TLS_CERT_DIR` must contain `fullchain.pem` and `privkey.pem`.

## 3. Preflight

Windows:

```powershell
.\scripts\ops\validate-production.ps1
```

Linux:

```bash
./scripts/ops/validate-production.sh
```

Preflight rejects remaining `CHANGE_ME` secrets, weak required secrets, an
HTTPS/TLS mismatch, missing certificate files, and invalid Compose syntax.

## 4. Deploy

Windows:

```powershell
.\scripts\ops\deploy-production.ps1
```

Linux:

```bash
./scripts/ops/deploy-production.sh
```

Deployment builds/starts the stack. The one-shot migration service must succeed
before the Go control plane starts. The deploy script waits for Gateway
`/readyz` before reporting READY.

Default localhost drill URLs:

```text
UI/API:     http://localhost:8080
Liveness:   http://localhost:8080/livez
Readiness:  http://localhost:8080/readyz
```

Direct host ports `8086`, `9572` and `9583` are intentionally not published by
the production Compose file.

## 5. Status and logs

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml ps
docker compose --env-file .env.production -f docker-compose.production.yml logs -f --tail=200 gateway backend-go runtime-python
```

Use `/livez` to determine whether the Gateway/process exists and `/readyz` to
determine whether user traffic should be admitted.

## 6. Manual migration

The production deployment runs migration automatically. To explicitly verify
or re-run the idempotent migration job:

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml run --rm migrate
```

A non-zero exit code is a deployment blocker.

## 7. Backup

Windows:

```powershell
.\scripts\ops\backup-production.ps1
```

Linux:

```bash
./scripts/ops/backup-production.sh
```

The backup temporarily stops the application and Milvus-side state services,
then restarts the stack in a `finally`/trap path. Backups are stored under
`backups/` by default and include checksums/manifest metadata.

**Not backed up:** `.env.production`, TLS private keys, external provider
credentials outside AgentMesh. Store those in an independent secret manager or
secure offline location.

## 8. Restore

Restore overwrites the configured configured data-volume namespace.

Windows:

```powershell
.\scripts\ops\restore-production.ps1 `
  -BackupDir ".\backups\agentmesh-YYYYMMDD-HHMMSS" `
  -Force
```

Linux:

```bash
./scripts/ops/restore-production.sh --force ./backups/agentmesh-YYYYMMDD-HHMMSS
```

Never point a validation restore at a volume prefix containing data you need.
For automated validation, use a unique `AGENTMESH_COMPOSE_PROJECT` and
`DATA_VOLUME_PREFIX`.

## 9. Rollback

Application rollback:

1. Keep the data backup taken before release.
2. Stop the current application services.
3. Deploy the previous accepted source/release package with the same env file.
4. Because database migrations are additive/idempotent, do not attempt ad-hoc
   reverse DDL.
5. If data/schema state itself must be rolled back, use the explicit restore
   workflow from the pre-release backup.

This separates code rollback from destructive data rollback.

## 10. Shutdown

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml down
```

Do **not** add `-v` unless you deliberately intend to destroy persistent data.

