# AgentMesh Ecosystem Security Boundaries


## Personal Model Pool / BYOK

- 每个个人模型服务拥有独立密钥；浏览器列表只接收 `maskedHint`，不会接收已保存明文。
- Go Control Plane 使用 AES-GCM 加密 API Key，并把 `userId + immutable serviceKey` 作为 AEAD associated data，避免跨用户/跨服务密文替换。
- `serviceId` 只作为浏览器 task-level routing intent；执行前必须再次按当前用户 ownership 和 enabled 状态解析。
- `manual` 选择不存在、已删除、已停用或不属于当前用户的服务时 fail-closed，不静默换到其他模型。
- 用户存在个人服务但没有任何服务加入自动路由时，自动模式 fail-closed，不静默回退到共享 Project Key。
- Durable Queue / Task 表只保存 `model_selection_json`；不保存 request-local Model Pool 或 API Key。Worker dispatch 时重新解密。
- Python Runtime 只为当前请求构造 Model candidate，不把个人凭据注册到全局 RuntimeContext。
- 图片任务要求候选服务显式配置视觉模型；文本-only 服务不会接收图片内容。
- Model route trace 只记录 service id/name、provider/model、模式和路由原因，不记录 Base credential。

## Service Account

- Raw API Key 仅创建时返回一次。
- 持久化只保存高熵 Key 的 SHA-256 hash 与 prefix。
- Key 校验使用 constant-time compare。
- Key 可撤销、可过期。
- Principal 固定绑定 Project。
- Service Account 创建者失去 Project DEVELOPER 权限后，机器身份不再继续授权。

## Public API

- Scope 最小权限。
- `Idempotency-Key` 防止外部重试产生重复执行。
- Task read 再次检查 Conversation → Project binding。
- Client 不能提交 projectId 来切换租户。
- Usage telemetry 不记录 raw API Key。

## Marketplace

- Manifest 为 typed closed schema。
- Secret-like fields 不属于 Manifest 模型。
- 远程 endpoint 限制 HTTPS 并阻断明显内网 / localhost 地址。
- 高风险网络/MCP权限要求 Project ADMIN。
- Private / Draft Package 不进入 Public Marketplace。
- Plugin 不作为任意远程代码执行入口。

## UI / Logging

- Service Account 列表只展示 prefix。
- Raw Key 只存在于一次性 reveal UI。
- Public topology、trace、audit 不应包含 API Key / secret hash / internal token。

## 仍需最终生产阶段完成

DNS rebinding、出站 egress proxy、云环境网络策略、Marketplace 签名/供应链证明、恶意包扫描属于 Final Production Closure / 后续生态强化，不在 开发包中伪装为已完成。
