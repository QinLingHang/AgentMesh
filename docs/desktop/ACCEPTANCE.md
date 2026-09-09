# Local Desktop Phase 1 Acceptance

Mandatory gates:

- Bridge refuses non-loopback bind configuration.
- Missing token or missing roots is fail-closed.
- Read/list/stat/search work only inside an authorized root.
- Read outside a root is denied.
- Symlink escape outside a root is denied.
- Sensitive credential paths and private-key suffixes are denied by default.
- Write/mkdir/copy suspend for P5 approval before side effects.
- Move/delete are high risk and suspend for approval.
- Reject leaves the filesystem unchanged.
- Approve executes the exact fingerprinted action once.
- Approved action is revalidated against current enabled/project-scoped Tool state.
- Official `local.fs.*` risk settings cannot be weakened through normal Tool CRUD.
- Desktop token is absent from React/API task payloads, persisted task JSON, trace, and browser-safe approval projection.
- Success and failure/denial attempts are auditable without logging file content or bridge tokens.
- Personal workspace and shared-project Tool scope remain isolated.
