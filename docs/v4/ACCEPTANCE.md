# AgentMesh V4 Platform Ecosystem Acceptance

V4 只有在代码级、真实 MySQL、SDK、React、Browser 和回归门禁全部执行时才能判定 PASS。

## 1. Go targeted

```powershell
cd backend-go
$env:P2_TEST_MYSQL_DSN="user:password@tcp(127.0.0.1:3306)/mysql?parseTime=true&charset=utf8mb4&multiStatements=true"
$env:P3_TEST_MYSQL_DSN=$env:P2_TEST_MYSQL_DSN
$env:P3_TEST_PYTHON=(Get-Command python).Source
go test ./internal/service -run '^TestV4' -count=1 -v
```

Mandatory scenarios：

- Service Account hash / scope / project isolation / revoke
- Marketplace validation / install / disable / enable / uninstall
- Public API idempotency / project binding

DB-backed V4 tests SKIP 不能算 PASS。

## 2. SDK

```powershell
cd sdk/python
python -m unittest discover -s tests -p "test_*.py" -v

cd ..\typescript
npm ci
npm test
```

## 3. React

```powershell
cd web-react
node --test tests/v4-platform-ecosystem-contract.test.mjs
npm test
npm run build
npm run test:e2e:v4
```

Browser 必须覆盖：Marketplace → 安装 → API/SDK → 一次性 Key → Publisher / Manifest validation。

## 4. Full regression

```powershell
cd runtime-python
python -m pytest -q

cd ..\backend-go
go test ./... -count=1

cd ..\web-react
npm test
npm run build
npm run test:e2e:p11
npm run test:e2e:p12-session
npm run test:e2e:v2
npm run test:e2e:v3
npm run test:e2e:v4
```

## 5. Security / source hygiene

必须确认：

- raw API Key 未持久化
- secret hash 不进入 API / UI
- revoked / expired key 失效
- scope enforcement
- public task project binding
- private endpoint validation
- high-risk permission ADMIN gate
- no runtime data / real secrets / local absolute paths
- development MANIFEST 完整

## 6. Final decision

最后一行必须是：

```text
V4 FINAL ACCEPTANCE = PASS
```

或：

```text
V4 FINAL ACCEPTANCE = FAIL
```
