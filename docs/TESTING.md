# AgentMesh Testing

AgentMesh tests live with the code they validate. There are no phase-chained
`TEST_P*.ps1` runners in the maintained project.

## 1. Go backend

Fast/unit regression:

```powershell
cd backend-go
go test ./... -count=1
```

Full MySQL-backed Project Runtime + Memory acceptance requires an administrator
DSN. The tests create and drop uniquely named test databases; they do not use
the database named in the DSN.

```powershell
$env:P2_TEST_MYSQL_DSN="user:password@tcp(127.0.0.1:3306)/mysql?parseTime=true&charset=utf8mb4&multiStatements=true"
$env:P3_TEST_MYSQL_DSN=$env:P2_TEST_MYSQL_DSN
$env:P3_TEST_PYTHON=(Get-Command python).Source

cd backend-go
go test ./... -count=1 -v
```

If the DSN variables are omitted, MySQL integration acceptance tests are
explicitly skipped instead of touching a developer database.

## 2. Python runtime

The pytest configuration supplies deterministic offline-safe defaults through
`tests/conftest.py`:

- `MODEL_PROVIDER=mock`
- `RAG_BACKEND=inmemory`
- `EMBEDDING_BACKEND=hash`
- `RERANKER_BACKEND=heuristic`
- `MEMORY_RETRIEVAL_ENABLED=false`

Run the suite directly:

```powershell
cd runtime-python
python -m pytest -q
```

Dedicated Memory tests inject deterministic writer/retrieval sources and still
exercise the production extraction, ranking, context-assembly, and HTTP paths.

## 3. React frontend

```powershell
cd web-react
npm test
npm run build
```

`npm test` validates the Memory Center contract and Run Details Memory-trace
privacy against the production formatter. `npm run build` remains the source of
truth for TypeScript/Vite compilation.

The current Vite bundle can emit a >500 kB chunk warning. That is a performance
backlog item, not a failed build when npm exits with code 0.

## 4. Full P3 automated acceptance

Run the three codebase-native suites above. For a full acceptance run, set the
MySQL DSNs before `go test` so the ownership, Project Runtime, Knowledge, and
Memory integration tests execute rather than skip.

No P2/P3 wrapper calls another P-stage wrapper. Historical phase runners were
removed after P3 closure; capability tests remain in the Go, Python, and React
codebases.

## 5. V2 Intelligence sprint

V2 multimodal RAG, advanced evaluation, cost accounting, and observability
acceptance is documented in `docs/v2/ACCEPTANCE.md`. The normal codebase-native
Python, Go, and React suites remain authoritative; V2 adds targeted coverage rather
than replacing earlier regressions.

Deterministic V2-specific entry points:

```powershell
cd runtime-python
python scripts/run_v2_eval.py

cd ..\web-react
npm run build
npm run test:e2e:v2
```

For full database-backed acceptance, both `P2_TEST_MYSQL_DSN` and
`P3_TEST_MYSQL_DSN` must be configured before Go/P12 execution. A missing DSN is
an environment blocker and must not be converted into a false PASS.

## 6. V3 Distributed Runtime sprint

V3 targeted acceptance is documented in `docs/v3/ACCEPTANCE.md`.

Convenience runner:

```powershell
$env:P2_TEST_MYSQL_DSN="user:password@tcp(127.0.0.1:3306)/mysql?parseTime=true&charset=utf8mb4&multiStatements=true"
$env:P3_TEST_MYSQL_DSN=$env:P2_TEST_MYSQL_DSN
$env:P3_TEST_PYTHON=(Get-Command python).Source

.\scripts\TEST_V3_DISTRIBUTED_RUNTIME.ps1 -Python $env:P3_TEST_PYTHON
```

Native commands remain authoritative:

```powershell
cd runtime-python
python -m pytest -q tests/test_v3_distributed_runtime.py
python -m pytest -q

cd ..\backend-go
go test ./internal/service -run '^TestV3' -count=1 -v
go test ./... -count=1

cd ..\web-react
npm test
npm run build
npm run test:e2e:v3
```

The V3 Go tests require an isolated MySQL DSN and must not be accepted as PASS
when skipped. The browser runner validates the sanitized multi-node topology and
a deterministic dispatcher/node failover transition; database integration tests
remain authoritative for lease, fencing, capacity and reassignment semantics.
