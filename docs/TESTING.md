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

If the DSN variables are omitted, MySQL integration tests are
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

## 4. Full automated regression

Run the three codebase-native suites above. For a full database-backed run, set the
MySQL DSNs before `go test` so the ownership, Project Runtime, Knowledge, and
Memory integration tests execute rather than skip.

Legacy wrapper scripts are not chained together. Historical phase runners were
removed after their capabilities were moved into the Go, Python, and React
codebases.

## 5. Intelligence and multimodal testing

Multimodal RAG, advanced evaluation, cost accounting, and observability
capabilities are covered by the normal codebase-native
Python, Go, and React suites remain authoritative; Targeted tests add focused coverage rather
than replacing earlier regressions.

Targeted entry points:

```powershell
cd runtime-python
python scripts/run_v2_eval.py

cd ..\web-react
npm run build
npm run test:e2e:v2
```

For full database-backed acceptance, both `P2_TEST_MYSQL_DSN` and
`P3_TEST_MYSQL_DSN` must be configured before database-backed Go integration testing. A missing DSN is
an environment blocker and must not be converted into a false PASS.

## 6. Distributed Runtime

Targeted distributed-runtime validation:

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

The distributed-runtime Go tests require an isolated MySQL DSN and must not be accepted as PASS
when skipped. The browser runner validates the sanitized multi-node topology and
a deterministic dispatcher/node failover transition; database integration tests
remain authoritative for lease, fencing, capacity and reassignment semantics.


## 7. Platform Ecosystem

Platform ecosystem validation uses the native commands below.

Native commands:

```powershell
cd backend-go
go test ./internal/service -run '^TestV4' -count=1 -v

cd ..\sdk\python
python -m unittest discover -s tests -p "test_*.py" -v

cd ..\typescript
npm ci
npm test

cd ..\..\web-react
node --test tests/v4-platform-ecosystem-contract.test.mjs
npm test
npm run build
npm run test:e2e:v4
```

The platform integration suite requires a working MySQL DSN and must not be accepted when skipped. The SDK tests use local deterministic HTTP fixtures and do not require a model provider. Public API acceptance must preserve project binding, scope enforcement, idempotency, raw-key privacy and Marketplace permission boundaries.
