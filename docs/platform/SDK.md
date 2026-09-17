# AgentMesh Official SDKs

提供两个官方轻量客户端：

```text
sdk/python
sdk/typescript
```

两者只调用 `/openapi/v1`，不会访问内部 Go/Python Runtime endpoint。

## Python

```powershell
cd sdk/python
python -m unittest discover -s tests -p "test_*.py"
```

客户端仅使用 Python 标准库。

## TypeScript

```powershell
cd sdk/typescript
npm ci
npm test
```

客户端使用标准 `fetch`，测试通过本地 HTTP fixture 验证 Authorization、Idempotency-Key、query 和 error envelope。

## SDK contract

SDK 必须：

- Bearer API Key
- 支持 Idempotency-Key
- 不把 Key 写入磁盘
- 对非 2xx / envelope error 抛出结构化异常
- URL encode Marketplace slug
- 不暴露任何内部 Runtime token
