# MVP-0 Acceptance

The MVP is DONE only after all items are verified on the user's machine:

- [ ] MySQL + Redis start through Docker Compose.
- [ ] Go `go test ./...` and `go run ./cmd/server` pass.
- [ ] Python `pytest` passes and Uvicorn starts.
- [ ] React `npm run build` and `npm run dev` pass.
- [ ] Register/login/refresh/logout work.
- [ ] User A cannot read User B's resources.
- [ ] Demo Agent Pool can be created dynamically.
- [ ] Fixed / Capability / Greedy schedulers can switch.
- [ ] A multi-capability task generates multiple Agent DAG nodes.
- [ ] `DataAgentPrimary` simulated failure triggers `DataAgentBackup` fallback.
- [ ] Task result, selected Agents, cost, latency, DAG and Trace appear in Web UI.
- [ ] Agent feedback is written to `agent_runtime_metrics`.
- [ ] Extensions page shows Model/Agent/Scheduler plugins as READY.

Do not put measured performance numbers on the resume before benchmark/load-test evidence exists.
