# AgentMesh v1.0 Security and Tenant Boundaries

## Tenant model

```text
User
  ↓
Organization / Workspace
  ↓
Project
  ↓
Project Membership / Role
  ↓
Project Runtime + Project Knowledge + Governance
```

Project membership does not merge personal user scopes.

## Shared Project execution

For member B executing owner A's Project:

```text
Runtime actor / user_id        = B
User-global Memory             = B
Project Runtime configuration  = Project
Project Agent/Tool/MCP owner   = A / Project owner resource pool
Project Knowledge              = shared Project scope
A GLOBAL Knowledge             = NOT automatically shared
A user-global Memory           = NOT shared
A Secret plaintext             = NOT exposed to B/browser
```

## RBAC

Roles are ordered by Project authority:

```text
OWNER > ADMIN > DEVELOPER > VIEWER
```

Authorization is enforced at both front-door mutation boundaries and runtime
recheck boundaries. A stale or forged persisted binding must not bypass runtime
authorization.

## BYOK

- encrypted at rest with AES-GCM;
- Project-bound AAD;
- browser receives mask/hint only;
- plaintext exists only on the internal execution path where needed;
- request-local model configuration does not pollute a global model pool;
- secret-like values are redacted from Audit and public projection.

## Provider URL safety

Project model providers reject localhost, loopback, private and link-local targets
at the governance boundary. Runtime HTTP clients do not trust ambient proxy
environment for the Project BYOK path.

## Quota and fail-closed behavior

Governance checks request rate, concurrency, token/cost budget and tool-action
budget before runtime fall-through where required. Rejected execution must not
continue to Python Runtime.

## Production network boundary

The production Compose topology exposes the Gateway only. Go, Python Runtime,
MCP, MySQL, Redis, Milvus, etcd, MinIO and the static web container remain on the
Docker network.
