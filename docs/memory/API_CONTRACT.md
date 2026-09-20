# Memory API Contract

All `/api` endpoints require the existing JWT authentication middleware.

## Create

`POST /api/memories`

```json
{
  "category": "preference",
  "memoryKey": "coding.explanation_style",
  "content": "Explain unfamiliar Go syntax with Java comparisons.",
  "sourceType": "explicit_user",
  "confidence": 1.0
}
```

`sourceType` defaults to `explicit_user`, `confidence` defaults to `1.0`, and `status` defaults to `active`.

## List

`GET /api/memories`

Optional lexical filters:

- `category`
- `status`
- `keyword`
- `limit` (default 100, capped at 200)

The base Memory API does not depend on embedding/vector retrieval.

## Get

`GET /api/memories/:id`

A successful direct read updates `lastAccessedAt`.

## Update

`PATCH /api/memories/:id`

Any subset of the create fields may be supplied. An empty patch is rejected.

## Delete

`DELETE /api/memories/:id`

Deletion is hard delete, matching the current project's CRUD style.

## Internal runtime foundation contract

`GET /internal/v1/users/:userId/memories?limit=100`

Requires the existing `X-Internal-Token` middleware and returns active memories. This endpoint is isolated from Python prompt assembly at the API-contract layer.
