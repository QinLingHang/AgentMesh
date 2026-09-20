# Production Operations + Real Deployment
The operations layer turns the application into an operable deployment without changing
Agent, RAG, Memory, Governance, or distributed-runtime business semantics.

## Public / private network boundary

```text
Internet / Browser
        |
        v
   Gateway :80/:443            <- only host-published application service
   /      |      \
  /api   /      /readyz
   |    /          |
   v   v           v
React Nginx    Go Control Plane :8086   (Docker network only)
                    |
          +---------+---------+
          |                   |
          v                   v
      MySQL/Redis       Python Runtime :9572
                              |
                         Milvus / MCP
```

The browser uses a same-origin API (`/api`). Go, Python Runtime, MCP demo,
MySQL, Redis, Milvus, MinIO and etcd are not published to the host in the production topology.
production topology.

## Health model

- `/livez`: process/gateway liveness only. External dependency failure must not
  cause an orchestrator restart loop.
- `/readyz`: traffic admission.
  - Go requires MySQL and Redis.
  - Python requires initialized Registry/Engine/Knowledge scope and an accepting
    durable worker when the worker is enabled.
- `/health` remains for backwards-compatible local tooling.

## Migration lifecycle

`backend-go/cmd/migrate` is the production migration entrypoint. It invokes one
idempotent `db.Migrate()` chain covering Runtime, Workspace, Project Runtime,
Memory, Durable Runtime and Governance schema.

Production Compose starts a one-shot `migrate` service after MySQL is healthy.
`backend-go` cannot start until that job exits successfully. The server also
runs the same idempotent migration chain as a safety net for local/manual
startup; there is no second schema implementation.

## Gateway and TLS

`infra/gateway` contains one image with HTTP and HTTPS configurations.

- Without certificates and with `REQUIRE_TLS=false`, it serves HTTP. This is
  appropriate for localhost production drills or when TLS is terminated by an
  upstream load balancer.
- With `/etc/agentmesh/tls/fullchain.pem` and `privkey.pem`, HTTPS is selected.
- `REQUIRE_TLS=true` fails closed when either certificate file is missing.
- HTTPS enables TLS 1.2/1.3, HSTS, frame denial, nosniff and strict referrer
  policy. Port 80 redirects to HTTPS while retaining `/livez` for container
  health checks.

## Persistent state

Named volumes are isolated behind `DATA_VOLUME_PREFIX`:

- MySQL
- Redis AOF/RDB
- Milvus etcd metadata
- MinIO object data
- Milvus local data
- Project Knowledge object files

`AGENTMESH_COMPOSE_PROJECT` and `DATA_VOLUME_PREFIX` can be changed for an
isolated validation stack without touching a developer or production stack.

## Backup / restore boundary

The backup workflow creates:

- logical MySQL dump;
- Redis data volume archive after `SAVE`;
- Milvus / etcd / MinIO archives while those services are stopped;
- Project Knowledge volume archive;
- hashes/manifest.

Application traffic is stopped while non-MySQL state is snapshotted to avoid a
cross-store moving target. `.env.production` and TLS private keys are
intentionally excluded from backups and must be protected separately.

Restore is deliberately destructive and requires an explicit `-Force` (Windows)
or `--force` (Linux) flag. It recreates only the configured configured data-volume
namespace, imports the MySQL dump, restores state volumes, and restarts the
stack.

## Logging

All Compose services use Docker `json-file` rotation (`10m`, five files). This
bounds local disk growth while keeping application logs accessible via
`docker compose logs`.

## Security invariants

- Project BYOK secrets remain encrypted and project-scoped.
- `GOVERNANCE_MASTER_KEY` is mandatory in production Compose.
- Python model/reranker/embedding HTTP clients run with proxy trust disabled in
  the production topology.
- Only Gateway is publicly published; internal tokens and internal APIs remain
  on the Compose network.
