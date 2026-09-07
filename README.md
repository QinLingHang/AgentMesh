# AgentMesh Runtime MVP

AgentMesh is a multi-stack Agent platform with:

- **Go control plane** — authentication, users/conversations, Project Runtime,
  Agent/Tool/MCP control, MySQL ownership boundaries, and Memory CRUD/contracts.
- **Python Agent runtime** — planning/scheduling, RAG, automatic Memory write,
  Memory retrieval/ranking, context assembly, and runtime traces.
- **React + TypeScript frontend** — workspace, Projects, Knowledge, Memory Center,
  and Run Details observability.

## Core scope invariants

```text
Memory = User-global
Project Knowledge = strictly Project-scoped
Project Runtime = Project-scoped execution boundary
```

A Project can constrain Agent / Tool / MCP / Runtime Policy and its own
Knowledge. It does not create a separate long-term Memory scope.

## P3 long-term Memory

The current Memory capability includes:

- durable `user_memories` storage and per-user ownership;
- explicit and stable automatic Memory write;
- secret, temporary, and Project-local write filtering;
- authority-aware upsert (`manual > explicit_user > inferred_user`);
- user-global relevance retrieval with semantic/lexical fallback;
- retrieval-before-write and no same-turn self recall;
- separated context assembly for conversation, Memory, and Project Knowledge;
- Memory Center create/edit/delete;
- privacy-safe Memory observability in Run Details.

See `docs/memory-p3/` for the detailed design.


## Production operations (P10)

P10 adds the release-oriented deployment plane: a single public Gateway,
same-origin API routing, liveness/readiness, an explicit migration job, optional
TLS, bounded Docker logs, and guarded backup/restore workflows. Start with
`docs/p10/RUNBOOK.md`; the production topology is `docker-compose.production.yml`.

## Development

This repository is maintained as normal project source. Development changes are
made directly in `backend-go`, `runtime-python`, and `web-react`; P-stage apply
and nested test-wrapper scripts are not part of the maintained architecture.

## Testing

Run tests directly from each component:

```powershell
cd backend-go
go test ./... -count=1

cd ..\runtime-python
python -m pytest -q

cd ..\web-react
npm test
npm run build
```

Full MySQL integration acceptance requires test DSNs; see `docs/TESTING.md`.

After automated P3 verification is green, use
`docs/memory-p3/P3_FINAL_ACCEPTANCE.md` for the single final manual acceptance.

## Local configuration

Use the checked-in `.env.example` files as templates. Real `.env` files, logs,
local backups, generated bundles, and `node_modules` are intentionally excluded
from the maintained source package.

## AgentMesh v1.0 Release Candidate (P12)

The maintained release identity is now **`v1.0.0-rc.1`**. P12 freezes feature
scope and packages the P1–P11 platform for one final human acceptance pass.

Release entry points:

- `docs/p12/FINAL_RELEASE.md` — RC scope, promotion rule, release artifacts;
- `docs/p12/RELEASE_CHECKLIST.md` — automated/operational/security release gates;
- `docs/p12/FULL_MANUAL_ACCEPTANCE.md` — the user's final end-to-end acceptance;
- `docs/p12/SECURITY_BOUNDARIES.md` — RBAC/IDOR/Knowledge/Memory/BYOK boundaries;
- `docs/p12/DEMO_SCRIPT.md` — 8–12 minute product demo path;
- `docs/p12/INTERVIEW_GUIDE.md` and `docs/p12/RESUME_PROJECT.md` — job-facing material;
- `docs/p12/CODEX_P12_VALIDATION.md` — final automated RC validation contract.

Production operations remain documented in `docs/p10/RUNBOOK.md`; browser
productization evidence is summarized in `docs/p11/P11_COMPLETION.md`.

The RC must **not** be promoted to `v1.0.0` until P12 automated validation and
`FULL MANUAL ACCEPTANCE` both pass.

## License

AgentMesh is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
