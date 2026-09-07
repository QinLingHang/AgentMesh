# AgentMesh V2 Intelligence Acceptance

This document describes the mandatory validation for the V2 development sprint. It is not a claim that every gate has already passed in every environment.

## Development identity

This sprint is an **unreleased development snapshot**. The working version is `2.0.0-dev`, based on the frozen public release `v1.0.0-rc.2`. It must not be tagged or published as a Release until the full V2 acceptance below passes. The root `MANIFEST.json` in a V2 development source package is therefore a development-integrity manifest, not a public release manifest.

## Python

```powershell
cd runtime-python
python -m pytest -q
python scripts/run_v2_eval.py
```

The deterministic evaluation runner must support both direct-script and module execution:

```powershell
python scripts/run_v2_eval.py
python -m scripts.run_v2_eval
```

Mandatory V2 coverage includes:

- deterministic Vision Provider
- request-local BYOK Vision handoff without browser projection
- explicit `visionModelName` gate for knowledge-image BYOK
- image/PDF provider error redaction before persistence
- image evidence ingestion
- PDF text layer
- PDF visual fallback and page limit
- TEXT / VISUAL / HYBRID classification
- modality filtering and evidence diversity
- multimodal provenance/citation projection
- deterministic Judge
- evaluation dataset/regression comparison
- token/cost semantics
- multimodal RAG observability

A real Vision/Model Judge smoke test is environment-dependent; deterministic contracts are mandatory.

## Go

```powershell
cd backend-go
go test ./... -count=1
```

For MySQL-backed integration tests, use an administrator DSN because the acceptance fixtures create and drop isolated temporary databases:

```powershell
$env:P2_TEST_MYSQL_DSN="user:password@tcp(127.0.0.1:3306)/mysql?parseTime=true&charset=utf8mb4&multiStatements=true"
$env:P3_TEST_MYSQL_DSN=$env:P2_TEST_MYSQL_DSN
go test ./... -count=1 -v
```

When using the repository's local development `docker-compose.yml`, an isolated local-only example is:

```powershell
docker compose up -d mysql redis
$env:P2_TEST_MYSQL_DSN="root:root123456@tcp(127.0.0.1:3310)/mysql?parseTime=true&charset=utf8mb4&multiStatements=true"
$env:P3_TEST_MYSQL_DSN=$env:P2_TEST_MYSQL_DSN
```

These credentials are the checked-in development-compose fixture values only; production credentials must never be substituted into acceptance commands.

V2 Go acceptance covers schema migration, multimodal knowledge metadata, run-cost accumulation, user/project isolation, project-wide aggregation, provider/model filters, and invalid time-range rejection.

## React

```powershell
cd web-react
npm test
npm run build
npm run test:e2e:p11
npm run test:e2e:v2
```

`test:e2e:v2` is the mandatory offline-safe deterministic browser flow. It uses synthetic image/Run fixtures and a real built React application in headless Chrome/Edge; it does not require a paid Vision provider or MySQL.

The P12 real-session browser regression remains a separate real-MySQL gate:

```powershell
npm run test:e2e:p12-session
```

V2 contract coverage includes Knowledge Center multimodal state, RAG Trace multimodal evidence, advanced scorecard dimensions, token/cost views, and cost APIs.

## End-to-end gate

Before V2 is closed, a complete local or staging flow must validate:

```text
login
-> project
-> upload synthetic image/PDF
-> knowledge becomes READY
-> visual/text evidence counts visible
-> run visual or hybrid query
-> final answer + valid citation
-> Run Details RAG trace
-> evaluation scorecard
-> usage/cost telemetry
```

Use mock/deterministic Vision for the mandatory offline-safe E2E. The repository-provided runner is:

```powershell
cd web-react
npm run build
npm run test:e2e:v2
```

It validates the browser path from synthetic image upload through READY multimodal state, HYBRID run, citation provenance, RAG Trace, advanced evaluation, and usage/cost telemetry. A configured real VLM is an additional smoke test.

## Security/privacy gate

Mandatory checks:

- no real secret/API key/private key in source or fixtures;
- no raw base64 image/document body in trace;
- visual/provider error persistence redacts secret-like material;
- user/project knowledge isolation remains intact;
- project cost access requires governance authorization; unrelated users are intentionally hidden with not-found semantics (existing P9 IDOR contract), not forbidden semantics;
- runtime data directories and uploaded knowledge are not tracked;
- test knowledge assets are synthetic only.

## V2 closure rule

V2 may be marked PASS only after mandatory Python, Go, React, build, integration/isolation, and hygiene gates have actual successful output. Environment-dependent real-provider smoke tests must be reported separately rather than converted into false production failures or false PASS claims.

## Closure #3 regression contracts

- P11 browser navigation follows the current product headings: navigation `任务记录` opens page heading `任务`; the Workspace identity is the breadcrumb `工作台`, while `.workspace-title` is the active conversation title.
- The dedicated V2 browser runner uses the Workspace breadcrumb instead of assuming the conversation title equals `工作台`.
- P12 browser cleanup is bounded: browser CDP close cannot block the runner indefinitely, and spawned browser/Vite/Go processes are terminated and awaited before the command exits.
- P9 shared-project execution remains BYOK-only. Its integration fixture now configures an explicit Project-owner model provider; no platform/global API-key fallback is introduced.
## Closure #4 regression contracts

- P11 governance browser acceptance explicitly opens the collapsed `高级安全与模型设置` and `审计记录` sections before asserting masked-secret and audit-actor content. Hidden detail rows are no longer treated as always-visible UI.
- P11 productization contract now validates the current Workspace breadcrumb contract instead of the stale `.workspace-title == 工作台` assumption.
- V2 browser citation acceptance follows the product's stable `SOURCES` disclosure (`.citation-source-summary` -> `.citation-source-details`) and validates page/modality provenance there; it no longer assumes every Markdown citation renders an inline `aria-label` marker.
- P12 standalone browser acceptance bounds Windows `taskkill`, browser shutdown, Vite/Go child cleanup, browser-profile cleanup, and fixture cleanup. After successful cleanup it explicitly exits `0`, preventing lingering Node/CDP/child-process handles from keeping the mandatory command alive indefinitely.

## Closure #5 — Browser label normalization

The V2 browser acceptance must validate the rendered retrieval-mode semantics rather than CSS letter casing.
The overview metric label is authored as `Retrieval Mode`, while the current UI style renders it as `RETRIEVAL MODE`.
The deterministic browser runner therefore normalizes rendered text with `toUpperCase()` before asserting `RETRIEVAL MODE` and `HYBRID`.
This is a test-contract correction only; no production UI behavior is changed.

## Closure #6 — Usage/cost rendered-label normalization

The V2 browser acceptance applies the same rendered-text normalization to usage/cost telemetry as to retrieval mode.
The production component authors the metric label as `Model Cost`, while CSS can render the visible browser text as `MODEL COST`.
The deterministic browser runner therefore normalizes `document.body.innerText` with `toUpperCase()` and validates `MODEL COST`, `MOCK-V2-VISION`, and the deterministic `$0.0042` value.
The same normalization is applied to the RAG-trace fixture identity/visual type (`v2-architecture.png` / `architecture`) so CSS casing cannot create another false negative after the usage/cost gate.
This is a test-contract correction only; no production React component or runtime behavior is changed.
