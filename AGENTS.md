# Repository Guidelines

- 除非我明确要求或者必须，否则避免使用降级处理、兜底方案、临时补丁、启发式方法、局部稳定化手段、以及非严谨通用算法的后处理补救措施。

- 在生成SQL时，需要确保生成的sql可以在目标数据库中正确的执行。

- 在回答的最后需要加上我们当前在做什么或者在讨论什么，比如：当前在做：调整每日采集任务的时间。但是不要落到文件中，只是在回答中展示。

- 我和你的约定内容不要放到文件中。

- 除非我明确要求，否则不写单元测试。

- 在使用plan模式完成改造并确认后，启动一个子代理使用codex的/review功能来验证改造落点是否符合plan中的内容，以及是否有不足和建议改进。需要把plan中的内容发给子代理。子代理仅分析。子代理模型和思考深度与主代理一致。子代理启动后，主代理就要等待子代理完成后再继续。只验证代码改造，方案等其他文件的改造都不用子代理验证。

- 在在完成plan模式后给我回答后，回答中要包含这次改动的逻辑。

- 不要更改readme文件。

- 数据库操作除非我有明确要求，否则只执行select语句，非select语句需要给我展示出来由我批准才能执行，select语句无需我批准。

- 代码设计原则尽量遵循SOLID原则，接口开发规范遵循restful规范。

- 在验证代码逻辑时，不要参考注释的内容，以免误导。

- 减少新建方法，除非要写的方法行数特别大（200行以上）。

- 在验证代码逻辑时，不要参考注释的内容，以免误导。

- 如果在写代码时，有更优的方法，则不用参照其它代码的写法。但代码习惯需要参考，比如日志、注释等非功能代码内容

- 在读取docx、pdf等文件内容时，不能忽略文件内的图片内容。

- 新增/修改代码时，关键功能要有详细且清晰的注释，但方案内容和我与你之间的对话内容不必写在注释中。

- 新增/修改代码时，关键位置要打印log日志。

- 当我说的提示词中包含分析时，代表我不需要改动代码，只分析问题。

- 当我说的提示词中包含解释时，代表我不需要改动代码，只分析问题。

- 当前项目生成的文档位置都要存放于当前项目的codex-generate目录中。

## Project Structure & Module Organization

`backend-go/cmd` and `backend-go/internal` contain Go entry points and control-plane code. `runtime-python/app` is the FastAPI runtime; `web-react/src` contains the React UI and styles. `desktop-bridge/` adds desktop integration; `sdk/python` and `sdk/typescript` hold API clients. Find infrastructure and schemas in `infra/` and `docker-compose*.yml`, scripts in `scripts/`, and architecture notes in `docs/`. Tests live with each module (`*_test.go`, `tests/`, or `web-react/tests/`).

## Build, Test, and Development Commands

Run commands from the named module directory unless noted otherwise:

- `docker compose up -d mysql redis kafka etcd minio milvus` from the root starts local infrastructure.
- `cd backend-go; go run ./cmd/server` starts the API; `go test ./... -count=1` runs its tests.
- `cd runtime-python; python -m uvicorn app.main:app --port 9572` starts the runtime; `python -m pytest -q` runs its offline-safe suite.
- `cd web-react; npm ci; npm run dev` starts Vite; `npm test` runs Node contract tests; `npm run build` checks TypeScript and builds assets.

## Coding Style & Naming Conventions

Match nearby code. Format Go with `gofmt`; use `_test.go` for tests. Python uses four spaces, `snake_case`, and `test_*.py`. TypeScript/TSX uses two spaces, PascalCase components (for example, `WorkspaceWelcome.tsx`), and `*.test.mjs` contract tests. Both TypeScript projects enable strict type checking. No repository-wide lint or formatter command is configured.

## Testing Guidelines

Run the affected module's suite and build the UI after UI changes. Full Go MySQL acceptance needs `P2_TEST_MYSQL_DSN`, `P3_TEST_MYSQL_DSN`, and `P3_TEST_PYTHON` as detailed in `docs/TESTING.md`; omitted DSNs skip integration tests, not pass them. Python tests default to mock/in-memory services. For cross-module changes, run relevant SDK or browser E2E tests. No coverage threshold is configured.

## Commit & Pull Request Guidelines

Recent commits often use `feat:`, `fix:`, `docs:`, `chore:`, or scoped subjects such as `feat(p21): ...`; this is not enforced. Keep subjects concise. Pull requests should describe behavior, affected modules, tests and skips, configuration/schema impact, and linked issues when applicable. Include UI screenshots.

## Configuration & Agent Workflow

Copy settings from `backend-go/.env.example` and `runtime-python/.env.example`; never commit credentials. Avoid `docker compose down -v` where development data exists. After a Plan-mode code change is confirmed, launch a read-only subagent using `/review` and the `code-review` skill to check plan alignment and defects; wait for its result. Non-code changes do not need this review.
