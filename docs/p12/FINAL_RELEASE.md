# P12 Final Release — AgentMesh v1.0.0-rc.1

## Goal

P12 freezes feature scope and converts the validated P1–P11 platform into a
release candidate that is reproducible, explainable, demonstrable, and ready for
one final human acceptance pass.

P12 does **not** add another Agent feature. Its deliverable is the release system
around the already validated platform.

## Release identity

```text
Current candidate: AgentMesh v1.0.0-rc.1
Final target:      AgentMesh v1.0.0
```

`v1.0.0` may be published only when both conditions are true:

1. `P12 FULL AUTOMATED VALIDATION: PASS`
2. `FULL MANUAL ACCEPTANCE: PASS`

Until then, all archives and screenshots must keep the RC identity.

## Validated platform baseline

The release candidate contains the cumulative P1–P11 platform:

- Go Control Plane
- Python Agent Runtime
- React/TypeScript product UI
- user/conversation/project control plane
- Agent / Tool / MCP registry and execution
- Project Knowledge / RAG and user-global Memory
- HITL / secure actions
- Eval / cost / latency governance
- adaptive Agent / Model routing
- durable distributed runtime with lease/fencing/recovery/backpressure
- enterprise multi-tenant governance, RBAC, IDOR defense, BYOK, quota and audit
- production operations, migrations, readiness/liveness, Gateway, TLS mode,
  backup/restore and deployment runbook
- real-browser product E2E, lazy loading, product error UX and strict bundle gate

## Release boundaries

The following are intentionally outside v1.0 scope:

- Kubernetes / Helm / Terraform
- cloud-vendor-specific deployment
- a second scheduler/runtime
- a second long-term Memory scope
- enterprise SSO/SCIM
- billing provider integration
- full observability-vendor integration
- mobile client

These are future roadmap items, not missing P12 requirements.

## Release artifacts

Required release-candidate artifacts:

- `VERSION`
- `MANIFEST.json`
- root `README.md`
- `docs/p12/RELEASE_CHECKLIST.md`
- `docs/p12/FULL_MANUAL_ACCEPTANCE.md`
- `docs/p12/DEMO_SCRIPT.md`
- `docs/p12/INTERVIEW_GUIDE.md`
- `docs/p12/RESUME_PROJECT.md`
- `docs/p12/SECURITY_BOUNDARIES.md`
- `docs/p12/CODEX_P12_VALIDATION.md`
- `scripts/release/validate-release.py`
- `scripts/release/stage-release.py`
- Windows/Linux release packaging scripts


## Release packaging model

P12 deliberately separates the active development worktree from the release payload.
A working checkout may legitimately contain local `.env` files, `.venv`, `node_modules`,
`dist`, caches or local backup artifacts. Those files are **never** release inputs.

The release flow is:

```text
development worktree
    ↓ identity/docs validation
clean temporary staging/export
    ↓ strict-tree validation
AgentMesh_v1.0.0-rc.1_SOURCE.zip
    ↓ archive privacy/integrity scan
release candidate
```

The staging step excludes environment files, dependency/build directories, caches,
logs, nested archives, browser profiles, TLS/private-key material and source backup
files such as `*.bak`. This makes packaging reproducible without deleting the user's
local development environment.

## Final promotion rule

After the user completes the full manual checklist with no mandatory failure:

```text
v1.0.0-rc.1
    ↓
FULL MANUAL ACCEPTANCE: PASS
    ↓
update VERSION/MANIFEST/package version to 1.0.0
    ↓
build clean final archive
    ↓
AgentMesh v1.0.0 RELEASE
```
