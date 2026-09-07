# AgentMesh v1.0 Full Manual Acceptance

> Execute only after P12 automated validation passes. This is the user's final
> human acceptance, not a Codex task.

Record each item as `PASS`, `FAIL`, or `N/A (with reason)`.

## 0. Preconditions

- use the exact P12 RC archive that passed Codex;
- keep real secrets out of screenshots/logs;
- use dedicated QA users/projects/knowledge/secrets;
- do not run destructive restore against valuable local data;
- keep the RC version until every mandatory item passes.

## 1. Environment and startup

1. Start development/QA infrastructure.
2. Start Python Runtime.
3. Verify Python `/livez` and `/readyz`.
4. Start Go Control Plane.
5. Verify Go `/health`, `/livez`, `/readyz`.
6. Start React development UI or validated production UI.
7. Confirm no startup panic/migration error.

Expected: all services reachable and readiness reflects actual dependency state.

## 2. Authentication and base shell

1. Register/login QA user A.
2. Refresh browser and confirm session restoration.
3. Logout/login again.
4. Trigger one invalid login path and confirm friendly error.

Expected: no blank screen; session and error UX are stable.

## 3. Project / Conversation / Agent smoke

1. Create Project `V1-FINAL-QA`.
2. Create/open a Project conversation.
3. Create or select a usable Agent.
4. Execute a normal task.
5. Confirm final answer renders.
6. Open Run Details; verify trace/DAG/latency/cost evidence where applicable.

## 4. Project Runtime

1. Bind selected Agent/Tool/MCP/Runtime policy.
2. Refresh and confirm persistence.
3. Execute again and confirm selected resource is used.

## 5. Project Knowledge

1. Upload Project Knowledge containing marker `PROJECT_V1_QA_92731`.
2. Ask a grounded question.
3. Confirm the answer can use the Project marker/evidence.
4. Confirm another unrelated Project cannot access it.

## 6. User-global Memory

1. User A creates marker `USER_A_MEMORY_V1_74826`.
2. Confirm Memory Center persistence.
3. Confirm retrieval where policy allows.
4. Create user B and confirm B cannot see A's Memory.

## 7. Tool / MCP / HITL

1. Confirm Tool registry opens and CRUD works for a QA Tool.
2. Confirm MCP registry/discovery path works with a safe QA endpoint/demo server.
3. Exercise a secure/HITL action path.
4. Confirm denied/unapproved actions do not silently execute.

## 8. Organization / Workspace

1. User A creates `AgentMesh V1 QA Org`.
2. Add user B.
3. Bind `V1-FINAL-QA` Project.
4. Refresh and confirm persistence.

## 9. Project RBAC and IDOR

Use A as OWNER, B as role-changing member, C as outsider.

### B = DEVELOPER
- can discover/open shared Project;
- can execute permitted Project work;
- cannot perform ADMIN/OWNER governance actions.

### B = VIEWER
- can read permitted Project views;
- cannot bind/execute at Developer boundary;
- runtime must not fall through after denial.

### B = ADMIN
- can perform admin governance actions allowed by contract;
- does not become OWNER.

### C = outsider
- cannot discover/read/execute Project by guessed ID.

## 10. Shared Project resource boundary

1. A owns Agent `OWNER_ONLY_V1_AGENT`.
2. B owns `MEMBER_ONLY_V1_AGENT`.
3. Project selects A's Agent.
4. B as DEVELOPER executes Project work.
5. Verify Run Details uses A's Project resource configuration.
6. Verify runtime actor/user remains B.

Expected: execution-resource owner and user identity remain deliberately separate.

## 11. Knowledge / Memory isolation in shared Project

1. A Project Knowledge marker: `PROJECT_SHARED_V1_92731`.
2. A GLOBAL Knowledge marker: `OWNER_GLOBAL_V1_61482`.
3. A Memory marker: `OWNER_MEMORY_V1_74826`.
4. B executes inside A's shared Project.

Expected:
- Project marker can be shared;
- owner's GLOBAL Knowledge is not automatically shared;
- owner's user-global Memory is not shared;
- B keeps B's Memory scope.

## 12. BYOK Secret and Project Model Provider

Use a fake/manual QA secret unless performing an explicitly safe real-provider test.

1. Create Project secret `P9_MANUAL_API_KEY` with unique plaintext marker.
2. Save and refresh.
3. Confirm UI shows mask/hint only.
4. Inspect Network response; plaintext must be absent.
5. Attempt localhost/loopback provider URL and confirm rejection.
6. Configure an allowed HTTPS provider URL and bind the Secret.
7. Confirm another Project cannot bind/read this Secret.

Optional: make one real request using a disposable test key.

## 13. Quota / Usage

1. Temporarily set request/minute to a small value and trigger rejection.
2. Confirm rejected request does not execute Runtime work.
3. Exercise token/cost/tool-action limits with safe QA values.
4. Confirm Usage changes after successful execution and survives refresh.
5. Restore normal limits.

Concurrent-task denial may rely on automated evidence if a stable manual long-run
fixture is unavailable; record that reason explicitly.

## 14. Audit / Redaction

Perform member, quota, Secret and Provider operations.

Verify Audit shows:
- When
- Who / actor
- Action
- Resource
- Result

Verify plaintext password/token/credential/secret/key/OTP-like values are absent.

## 15. Permission revocation

1. Remove B from the shared Project.
2. Refresh B.
3. Confirm Project disappears or access is denied.
4. Confirm stale open UI cannot continue privileged reads/execution.

## 16. Product UX / Browser regression

1. Navigate Agents, Knowledge, Extensions, Tasks, Governance.
2. Confirm no blank-screen transition.
3. Confirm lazy-loaded modules render.
4. Trigger representative 403/404/409/429/5xx/network errors where safe.
5. Confirm actionable Chinese error messages.

## 17. Production operations manual smoke

When Docker Hub/network access is available:

1. initialize unique production env;
2. run production preflight;
3. build/start production Compose;
4. confirm Gateway is the public application boundary;
5. verify Gateway `/livez`/`/readyz` routes;
6. restart backend/runtime and confirm recovery;
7. create safe sentinel data;
8. run backup;
9. restore only in an isolated disposable stack;
10. verify sentinel round trip;
11. shut down without deleting named data volumes.

If Docker Hub remains externally blocked, record exact external error and retain the
P10 static/automated evidence. Do not mislabel an external registry failure as a
project-code PASS or FAIL.

## 18. Release UX review

- main UI language is natural Chinese;
- final answer remains visually separate from Run Details;
- governance/security language is understandable;
- empty/loading/error states are acceptable;
- no obvious debug/test-only text leaks into normal UI.

## 19. Final acceptance record

```text
Environment / Startup                 PASS / FAIL
Authentication                        PASS / FAIL
Project / Conversation / Agent        PASS / FAIL
Project Runtime                       PASS / FAIL
Knowledge                             PASS / FAIL
Memory                                PASS / FAIL
Tool / MCP / HITL                     PASS / FAIL
Organization / Workspace              PASS / FAIL
RBAC / IDOR                           PASS / FAIL
Shared Project Execution              PASS / FAIL
Knowledge / Memory Isolation          PASS / FAIL
BYOK / Provider                       PASS / FAIL
Quota / Usage                         PASS / FAIL
Audit / Redaction                     PASS / FAIL
Permission Revocation                 PASS / FAIL
Product UX                            PASS / FAIL
Production Operations                 PASS / FAIL / ENV-BLOCKED

FULL MANUAL ACCEPTANCE: PASS / FAIL
```

Only `FULL MANUAL ACCEPTANCE: PASS` permits promotion to `v1.0.0`.


## Session restoration refresh check

After a successful login, press **F5** and **Ctrl+F5** on an authenticated page. The application must remain authenticated and restore the current product shell through the HttpOnly refresh-cookie flow. Returning to the login screen is a FAIL. This must work whether the Vite development UI is opened with `localhost:5173` or `127.0.0.1:5173`.
