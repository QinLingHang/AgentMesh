# AgentMesh V3 Acceptance

V3 is a development sprint and is not a public release.

## Mandatory functional gates

- V2 full regression remains green.
- Two or more Runtime workers can register with explicit node identity.
- Multiple workers on one node cannot exceed effective node capacity.
- Scheduler prefers lower authoritative worker/node load.
- stale/draining/circuit-open workers are not scheduled.
- dispatcher lease elects only one active dispatcher.
- dispatcher ownership transfer increments epoch.
- pre-accept lease recovery is safe.
- accepted worker-loss replay is opt-in.
- safe accepted jobs can be reassigned cross-node.
- unsafe accepted jobs fail closed.
- stale fence callbacks cannot commit results.
- execution lease renewal validates worker/execution/lease/fence tuple.
- topology API never leaks worker endpoint or credentials.
- Python graceful drain rejects new work but preserves current executions.
- Tasks UI displays sanitized node/worker/queue/dispatcher state.
- Run Details displays node/fence/dispatcher metadata.

## Required automated suites

Python:

```text
pytest -q tests/test_v3_distributed_runtime.py
pytest -q
```

Go with isolated MySQL:

```text
go test ./internal/service -run '^TestV3' -count=1 -v
go test ./... -count=1
```

React:

```text
npm test
npm run build
```

Production/multi-node validation must additionally prove dispatcher takeover and worker/node-loss behavior with isolated test infrastructure. Environment blockers must never be reported as PASS.

## Security gates

- no worker endpoint in browser topology JSON;
- no internal token / lease token / BYOK secret in browser or trace;
- no runtime upload/data tracked by Git;
- test credentials are synthetic;
- unsafe accepted execution is never automatically replayed.
