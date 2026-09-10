"""Minimal dependency-free AgentMesh V4 public API client."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(slots=True)
class AgentMeshError(Exception):
    status: int
    code: int | None
    message: str
    data: Any = None

    def __str__(self) -> str:
        suffix = f" (code={self.code})" if self.code is not None else ""
        return f"AgentMesh API {self.status}: {self.message}{suffix}"


class AgentMeshClient:
    """Project-scoped V4 Public API client using a Service Account API key."""

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout
        if not self.base_url or not self.api_key:
            raise ValueError("base_url and api_key are required")

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        query: Mapping[str, str | int | None] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        url = self.base_url + path
        if query:
            encoded = urllib.parse.urlencode({k: v for k, v in query.items() if v is not None and v != ""})
            if encoded:
                url += "?" + encoded
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "agentmesh-python-sdk/4.0.0-dev",
        }
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"message": raw or exc.reason}
            raise AgentMeshError(exc.code, payload.get("code"), payload.get("message", str(exc)), payload.get("data")) from exc
        except urllib.error.URLError as exc:
            raise AgentMeshError(0, None, f"network error: {exc.reason}") from exc
        if not isinstance(payload, dict):
            raise AgentMeshError(200, None, "invalid API envelope", payload)
        if payload.get("code", 0) != 0:
            raise AgentMeshError(200, payload.get("code"), payload.get("message", "API error"), payload.get("data"))
        return payload.get("data")

    def run_task(
        self,
        task: str,
        *,
        conversation_id: int | None = None,
        idempotency_key: str | None = None,
        scheduler: str = "adaptive",
        planner: str = "multi_objective",
        execution_mode: str = "auto",
        synthesis_mode: str = "auto",
        constraints: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "task": task,
            "scheduler": scheduler,
            "planner": planner,
            "executionMode": execution_mode,
            "synthesisMode": synthesis_mode,
            "constraints": dict(constraints or {}),
        }
        if conversation_id is not None:
            body["conversationId"] = conversation_id
        return self._request("POST", "/openapi/v1/tasks/run", body=body, idempotency_key=idempotency_key)

    def get_task(self, task_id: int) -> dict[str, Any]:
        return self._request("GET", f"/openapi/v1/tasks/{int(task_id)}")

    def marketplace(self, *, query: str = "", kind: str = "", limit: int = 50) -> list[dict[str, Any]]:
        return self._request("GET", "/openapi/v1/marketplace", query={"q": query, "kind": kind, "limit": limit})

    def package(self, slug: str) -> dict[str, Any]:
        return self._request("GET", "/openapi/v1/marketplace/" + urllib.parse.quote(slug, safe=""))
