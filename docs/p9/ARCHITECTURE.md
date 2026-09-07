# P9 Enterprise Governance + Multi-tenant Control Plane

P9 adds a governance plane without changing the core scope contract established in P1-P8.

## Scope hierarchy

```text
User
  ├─ User-global Memory              (still owned by the user)
  ├─ User-global Knowledge           (still private to the user)
  └─ Organization / Workspace
       └─ Project
            ├─ Project Members / RBAC
            ├─ Project Runtime
            ├─ PROJECT Knowledge
            ├─ Project Quota / Usage
            ├─ Project Secrets / BYOK
            └─ Project Audit
```

A project member can discover and use a shared Project according to role. Sharing a Project never shares the project owner's User-global Memory or GLOBAL Knowledge.

## Project RBAC

Roles are ordered:

`OWNER > ADMIN > DEVELOPER > VIEWER`

- OWNER: project owner, full control.
- ADMIN: membership, quota, secret and model-provider governance.
- DEVELOPER: execute project tasks, use project runtime and shared PROJECT knowledge.
- VIEWER: read shared project metadata/knowledge but cannot execute or mutate protected resources.

Project mutation endpoints that predate P9 remain owner-safe unless explicitly routed through the governance service. P9 resource access is checked again at runtime before task execution.

## Secret/BYOK boundary

Project secrets are encrypted at rest with AES-256-GCM. The configured `GOVERNANCE_MASTER_KEY` is hashed into the AES key; local development falls back to `JWT_SECRET` only when the governance key is omitted. Production deployments should always provide a dedicated high-entropy key.

The browser can create/delete secrets and receives only `maskedHint`. There is no plaintext read API.

```text
Browser secret write
    ↓
Go Control Plane
    ↓ AES-GCM + project/name AAD
MySQL ciphertext
    ↓ internal decrypt only when required
request-local ProjectModelRuntime
    ↓ trusted internal request
Python Runtime
    ↓ request-local OpenAI-compatible provider (trust_env=False)
execution ends
```

Python never registers the Project BYOK provider into global `RuntimeContext`, preventing cross-project model-key contamination.

## Quota governance

Project quota currently covers:

- requests per minute (distributed DB minute bucket)
- concurrent active tasks
- monthly token usage
- monthly estimated cost
- daily tool actions

The Go control plane checks quota before project task execution/resume and records token/cost/tool usage after runtime completion/suspension. P8 durable dispatch keeps the same governance boundary.

## Audit/privacy

Governance actions emit project audit events with actor/action/resource/result. Metadata uses a strict secret-like-key redaction rule. Secret plaintext, token/password/credential/OTP fields are never intentionally stored in audit metadata.

## SSRF boundary

Project model-provider URLs must be HTTPS and reject localhost, loopback, private, link-local and unspecified literal IP destinations. Python request-local provider clients set `trust_env=False`. This is a baseline defense; production egress allowlists/network policy remain recommended.
