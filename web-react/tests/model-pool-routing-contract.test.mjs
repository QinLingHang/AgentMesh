import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");
const readProject = (relative) => fs.readFileSync(path.join(root, "..", relative), "utf8");

test("model settings exposes a multi-service BYOK pool instead of one overwrite-only config", () => {
  const settings = read("src/features/model-settings/ModelSettings.tsx");
  const api = read("src/api.ts");
  const types = read("src/types.ts");

  assert.match(settings, /我的模型服务/);
  assert.match(settings, /添加模型服务/);
  assert.match(settings, /自定义接口/);
  assert.match(settings, /加入自动路由/);
  assert.match(settings, /设为默认服务/);
  assert.match(settings, /DeepSeek、OpenRouter、vLLM/);
  assert.match(api, /\/api\/me\/model-services/);
  assert.match(api, /createUserModelService/);
  assert.match(api, /updateUserModelService/);
  assert.match(api, /deleteUserModelService/);
  assert.match(types, /export type UserModelService/);
  const projection = types.match(/export type UserModelService = \{([\s\S]*?)\n\};/)?.[1] ?? "";
  assert.ok(projection.length > 0);
  assert.doesNotMatch(projection, /apiKey:\s*string/);
});

test("workspace defaults to adaptive model selection and supports task-level manual override", () => {
  const workspace = read("src/features/workspace/Workspace.tsx");
  const api = read("src/api.ts");

  assert.match(workspace, /自动选择/);
  assert.match(workspace, /composer-model-trigger/);
  assert.match(workspace, /aria-haspopup="menu"/);
  assert.match(workspace, /aria-label="选择模型"/);
  assert.match(workspace, /mode:\s*"manual"/);
  assert.match(workspace, /modelSelection/);
  assert.match(api, /modelSelection:\s*input\.modelSelection \?\? \{ mode: "auto" \}/);
});

test("control plane persists only routing intent and re-resolves secrets at execution time", () => {
  const schema = readProject("backend-go/internal/db/user_model_schema.go");
  const service = readProject("backend-go/internal/service/governance.go");
  const durable = readProject("backend-go/internal/service/durable_runtime.go");
  const repo = readProject("backend-go/internal/repository/mysql.go");

  assert.match(schema, /user_model_services/);
  assert.match(schema, /ciphertext/);
  assert.match(schema, /model_selection_json/);
  assert.match(service, /ResolveUserModelRuntimePool/);
  assert.match(service, /ResolveRequestModelRuntimePool/);
  assert.match(service, /userModelServiceAAD/);
  assert.match(durable, /ModelSelection/);
  assert.match(durable, /resolveRequestModelRuntimePool/);
  assert.match(repo, /model_selection_json/);
  assert.doesNotMatch(schema, /api_key\s+(?:VARCHAR|TEXT|LONGTEXT)/i);
});

test("python runtime routes request-local BYOK candidates without registering secrets globally", () => {
  const runtime = readProject("runtime-python/app/models/runtime.py");
  const router = readProject("runtime-python/app/optimization/model_router.py");
  const interactive = readProject("runtime-python/app/services/interactive_stream.py");

  assert.match(runtime, /RequestLocalModelCandidate/);
  assert.match(runtime, /model_pool/);
  assert.match(runtime, /selection\.mode == "manual"/);
  assert.match(runtime, /has_images/);
  assert.match(router, /route_candidates/);
  assert.match(interactive, /model_route/);
  assert.match(interactive, /record_execution/);
  assert.doesNotMatch(runtime, /context\.provide\([^\n]*api_key/i);
});
