# AgentMesh Official SDKs

V4 提供 Python 与 TypeScript 官方 SDK，统一使用项目级 Service Account API Key、Scope 和 `Idempotency-Key`。SDK 只封装 `/openapi/v1` 公共接口，不绕过项目治理、配额、BYOK 或租户边界。

- Python：`sdk/python`
- TypeScript：`sdk/typescript`
- OpenAPI：`docs/v4/openapi.yaml`

完整说明见 `docs/v4/SDK.md` 与 `docs/v4/PUBLIC_API.md`。
