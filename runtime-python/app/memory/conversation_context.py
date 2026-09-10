from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from redis.asyncio import Redis

from app.models.contracts import ModelMessage, ModelRequest
from app.rag.embedding import HashEmbeddingProvider


@dataclass(frozen=True, slots=True)
class ConversationHistoryMessage:
    id: int
    role: str
    content: str
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class ConversationMemoryCapsule:
    id: int
    user_id: int
    conversation_id: int
    start_message_id: int
    end_message_id: int
    summary: str
    facts: tuple[str, ...]
    decisions: tuple[str, ...]
    open_tasks: tuple[str, ...]
    entities: tuple[str, ...]
    keywords: tuple[str, ...]
    importance: float
    source_hash: str
    compaction_model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievedConversationMemory:
    capsule: ConversationMemoryCapsule
    score: float
    semantic_score: float
    lexical_score: float
    recency_score: float


_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def _track_background(task: asyncio.Task[Any]) -> None:
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


class ControlPlaneConversationMemoryStore:
    """Durable conversation-memory boundary owned by the Go control plane."""

    def __init__(
        self,
        *,
        internal_token: str,
        base_url: str | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        configured = (
            base_url
            or os.getenv("AGENTMESH_CONTROL_PLANE_URL")
            or "http://127.0.0.1:8086"
        )
        self.base_url = configured.rstrip("/")
        self.internal_token = internal_token
        self.timeout_seconds = timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {"X-Internal-Token": self.internal_token}

    async def list_capsules(
        self,
        *,
        user_id: int,
        conversation_id: int,
        limit: int,
    ) -> list[ConversationMemoryCapsule]:
        safe_limit = max(1, min(int(limit), 200))
        async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
            response = await client.get(
                f"{self.base_url}/internal/v1/users/{user_id}/conversations/{conversation_id}/memory-capsules",
                headers=self._headers(),
                params={"limit": safe_limit},
            )
            response.raise_for_status()
            payload = response.json()
        raw_items = payload.get("data", payload)
        if not isinstance(raw_items, list):
            raise ValueError("conversation memory capsule response must contain a list")
        result: list[ConversationMemoryCapsule] = []
        for raw in raw_items:
            capsule = _parse_capsule(raw, user_id=user_id, conversation_id=conversation_id)
            if capsule is not None:
                result.append(capsule)
        return result

    async def compaction_window(
        self,
        *,
        user_id: int,
        conversation_id: int,
        after_id: int,
        min_messages: int,
        max_messages: int,
        reserve_recent: int,
    ) -> list[ConversationHistoryMessage]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
            response = await client.get(
                f"{self.base_url}/internal/v1/users/{user_id}/conversations/{conversation_id}/memory-compaction-window",
                headers=self._headers(),
                params={
                    "afterId": max(0, int(after_id)),
                    "minMessages": int(min_messages),
                    "maxMessages": int(max_messages),
                    "reserveRecent": int(reserve_recent),
                },
            )
            response.raise_for_status()
            payload = response.json()
        raw_data = payload.get("data", payload)
        raw_items = raw_data.get("items", []) if isinstance(raw_data, dict) else []
        result: list[ConversationHistoryMessage] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            try:
                message_id = int(raw.get("id"))
            except (TypeError, ValueError):
                continue
            role = str(raw.get("role", "")).strip().lower()
            content = str(raw.get("content", "")).strip()
            if message_id <= 0 or role not in {"user", "assistant"} or not content:
                continue
            request_id = raw.get("requestId")
            result.append(
                ConversationHistoryMessage(
                    id=message_id,
                    role=role,
                    content=content,
                    request_id=str(request_id) if request_id else None,
                )
            )
        return result

    async def upsert_capsule(
        self,
        *,
        user_id: int,
        conversation_id: int,
        payload: dict[str, Any],
    ) -> ConversationMemoryCapsule:
        async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
            response = await client.post(
                f"{self.base_url}/internal/v1/users/{user_id}/conversations/{conversation_id}/memory-capsules",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        raw = body.get("data", body)
        capsule = _parse_capsule(raw, user_id=user_id, conversation_id=conversation_id)
        if capsule is None:
            raise ValueError("invalid persisted conversation memory capsule")
        return capsule


class ConversationMemoryRetriever:
    """Cheap query-dependent recall over durable conversation capsules.

    Retrieval deliberately uses local deterministic embeddings + lexical overlap;
    it never adds another paid model call to an ordinary user request.
    """

    _token_pattern = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]")

    def __init__(
        self,
        *,
        store: ControlPlaneConversationMemoryStore,
        enabled: bool = True,
        candidate_limit: int = 80,
        top_k: int = 3,
        min_score: float = 0.12,
        max_chars: int = 3200,
    ) -> None:
        self.store = store
        self.enabled = enabled
        self.candidate_limit = max(1, min(candidate_limit, 200))
        self.top_k = max(1, min(top_k, 8))
        self.min_score = max(0.0, min(min_score, 1.0))
        self.max_chars = max(500, min(max_chars, 10000))
        self.embedding = HashEmbeddingProvider(dimension=256)

    async def retrieve(
        self,
        *,
        user_id: int,
        conversation_id: int | None,
        query: str,
    ) -> list[RetrievedConversationMemory]:
        if not self.enabled or conversation_id is None or not query.strip():
            return []
        capsules = await self.store.list_capsules(
            user_id=user_id,
            conversation_id=conversation_id,
            limit=self.candidate_limit,
        )
        if not capsules:
            return []

        texts = [query] + [_capsule_embedding_text(item) for item in capsules]
        vectors = await self.embedding.embed(texts)
        query_vector = vectors[0]
        query_tokens = _tokens(query)
        newest_end = max(item.end_message_id for item in capsules)
        broad_continuity_query = _is_broad_continuity_query(query)
        ranked: list[RetrievedConversationMemory] = []

        for capsule, vector in zip(capsules, vectors[1:]):
            semantic = max(0.0, _cosine(query_vector, vector))
            lexical = _lexical_score(query_tokens, _tokens(_capsule_embedding_text(capsule)))
            distance = max(0, newest_end - capsule.end_message_id)
            recency = 1.0 / (1.0 + (distance / 40.0))
            score = (
                0.52 * semantic
                + 0.28 * lexical
                + 0.12 * capsule.importance
                + 0.08 * recency
            )
            if not broad_continuity_query and lexical <= 0.0 and semantic < 0.18:
                continue
            if score < self.min_score:
                continue
            ranked.append(
                RetrievedConversationMemory(
                    capsule=capsule,
                    score=score,
                    semantic_score=semantic,
                    lexical_score=lexical,
                    recency_score=recency,
                )
            )

        ranked.sort(key=lambda item: (-item.score, -item.capsule.end_message_id))
        selected: list[RetrievedConversationMemory] = []
        used_chars = 0
        for item in ranked:
            estimated = len(render_capsule(item.capsule))
            if selected and used_chars + estimated > self.max_chars:
                continue
            selected.append(item)
            used_chars += estimated
            if len(selected) >= self.top_k:
                break
        return selected


class ModelBackedConversationCompactor:
    """Threshold-triggered LLM compression of old conversation messages.

    Compaction is auxiliary and fail-open:
    - raw MySQL messages are never deleted;
    - ordinary requests never wait for compaction;
    - failures back off and retry later;
    - a Redis lease prevents duplicate paid compaction across Runtime nodes.
    """

    def __init__(
        self,
        *,
        store: ControlPlaneConversationMemoryStore,
        enabled: bool = True,
        min_messages: int = 12,
        max_messages: int = 18,
        reserve_recent: int = 16,
        min_input_chars: int = 1200,
        max_input_chars: int = 10000,
        max_output_tokens: int = 600,
        timeout_seconds: float = 12.0,
        failure_backoff_seconds: float = 60.0,
        redis_url: str | None = None,
        lock_prefix: str = "agentmesh:conversation-memory:compact-lock",
        lock_ttl_seconds: int = 45,
    ) -> None:
        self.store = store
        self.enabled = enabled
        self.min_messages = max(4, min(min_messages, 40))
        self.max_messages = max(self.min_messages, min(max_messages, 40))
        self.reserve_recent = max(4, min(reserve_recent, 40))
        self.min_input_chars = max(0, min_input_chars)
        self.max_input_chars = max(1000, max_input_chars)
        self.max_output_tokens = max(200, min(max_output_tokens, 1200))
        self.timeout_seconds = max(3.0, min(timeout_seconds, 30.0))
        self.failure_backoff_seconds = max(5.0, min(failure_backoff_seconds, 600.0))
        self.lock_prefix = lock_prefix.rstrip(":")
        self.lock_ttl_seconds = max(15, min(int(lock_ttl_seconds), 180))
        self._redis = (
            Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
            if redis_url
            else None
        )
        self._inflight: set[tuple[int, int]] = set()
        self._retry_after: dict[tuple[int, int], float] = {}

    def _lock_key(self, user_id: int, conversation_id: int) -> str:
        return f"{self.lock_prefix}:{user_id}:{conversation_id}"

    async def _acquire_distributed_lock(
        self,
        user_id: int,
        conversation_id: int,
    ) -> str | None:
        if self._redis is None:
            return "local-only"
        token = uuid.uuid4().hex
        acquired = await self._redis.set(
            self._lock_key(user_id, conversation_id),
            token,
            nx=True,
            ex=self.lock_ttl_seconds,
        )
        return token if acquired else None

    async def _release_distributed_lock(
        self,
        user_id: int,
        conversation_id: int,
        token: str | None,
    ) -> None:
        if self._redis is None or not token or token == "local-only":
            return
        script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end"
        )
        try:
            await self._redis.eval(
                script,
                1,
                self._lock_key(user_id, conversation_id),
                token,
            )
        except Exception:
            return

    async def _eligible_window(
        self,
        *,
        user_id: int,
        conversation_id: int,
    ) -> tuple[int, list[ConversationHistoryMessage]]:
        capsules = await self.store.list_capsules(
            user_id=user_id,
            conversation_id=conversation_id,
            limit=1,
        )
        after_id = capsules[0].end_message_id if capsules else 0
        window = await self.store.compaction_window(
            user_id=user_id,
            conversation_id=conversation_id,
            after_id=after_id,
            min_messages=self.min_messages,
            max_messages=self.max_messages,
            reserve_recent=self.reserve_recent,
        )
        if len(window) < self.min_messages:
            return after_id, []

        source_chars = sum(len(item.content) for item in window)
        if source_chars < self.min_input_chars and len(window) < self.max_messages:
            return after_id, []
        return after_id, window

    async def compact_if_needed(
        self,
        *,
        user_id: int,
        conversation_id: int | None,
        model_gateway: Any,
        model_name: str,
    ) -> None:
        if (
            not self.enabled
            or conversation_id is None
            or model_gateway is None
            or not model_name.strip()
        ):
            return

        initial_after_id, window = await self._eligible_window(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if not window:
            return

        lock_token = await self._acquire_distributed_lock(user_id, conversation_id)
        if lock_token is None:
            return

        try:
            latest_after_id, latest_window = await self._eligible_window(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            if latest_after_id != initial_after_id:
                window = latest_window
            elif latest_window:
                window = latest_window
            if not window:
                return

            safe_messages = _bounded_safe_messages(window, self.max_input_chars)
            if len(safe_messages) < self.min_messages:
                return

            response = await asyncio.wait_for(
                model_gateway.generate(
                    ModelRequest(
                        model=model_name,
                        temperature=0.0,
                        max_tokens=self.max_output_tokens,
                        messages=[
                            ModelMessage(
                                role="system",
                                content=(
                                    "Compress an OLD range of one conversation into a durable memory capsule. "
                                    "Use ONLY the supplied messages. Preserve stable facts, decisions, user requirements, "
                                    "unfinished tasks and important entities. Drop greetings, repetition, transient logs, "
                                    "temporary timings and low-value chatter. Never copy passwords, API keys, tokens, cookies, "
                                    "private keys or credential values. Return strict JSON only with keys: summary (string), "
                                    "facts (array), decisions (array), open_tasks (array), entities (array), keywords (array), "
                                    "importance (0..1). Keep summary under 1200 characters and each array concise."
                                ),
                            ),
                            ModelMessage(
                                role="user",
                                content=json.dumps(
                                    {
                                        "messages": [
                                            {
                                                "id": item.id,
                                                "role": item.role,
                                                "content": item.content,
                                            }
                                            for item in safe_messages
                                        ]
                                    },
                                    ensure_ascii=False,
                                ),
                            ),
                        ],
                        timeout=self.timeout_seconds,
                    )
                ),
                timeout=self.timeout_seconds + 1.0,
            )

            parsed = _parse_compaction_json(response.content)
            source_hash = hashlib.sha256(
                "\n".join(
                    f"{item.id}|{item.role}|{item.content}"
                    for item in safe_messages
                ).encode("utf-8")
            ).hexdigest()
            payload = {
                "startMessageId": safe_messages[0].id,
                "endMessageId": safe_messages[-1].id,
                "summary": parsed["summary"],
                "facts": parsed["facts"],
                "decisions": parsed["decisions"],
                "openTasks": parsed["open_tasks"],
                "entities": parsed["entities"],
                "keywords": parsed["keywords"],
                "importance": parsed["importance"],
                "sourceHash": source_hash,
                "compactionModel": response.model or model_name,
                "inputTokens": max(0, int(response.input_tokens or 0)),
                "outputTokens": max(0, int(response.output_tokens or 0)),
                "estimatedCost": (
                    max(0.0, float(response.estimated_cost))
                    if response.estimated_cost is not None
                    else None
                ),
            }
            await self.store.upsert_capsule(
                user_id=user_id,
                conversation_id=conversation_id,
                payload=payload,
            )
        finally:
            await self._release_distributed_lock(
                user_id,
                conversation_id,
                lock_token,
            )

    def schedule(
        self,
        *,
        user_id: int,
        conversation_id: int | None,
        model_gateway: Any,
        model_name: str,
    ) -> None:
        if not self.enabled or conversation_id is None or model_gateway is None:
            return

        key = (user_id, conversation_id)
        now = time.monotonic()
        if key in self._inflight:
            return
        if now < self._retry_after.get(key, 0.0):
            return

        self._inflight.add(key)

        async def run() -> None:
            try:
                await self.compact_if_needed(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    model_gateway=model_gateway,
                    model_name=model_name,
                )
            except Exception:
                self._retry_after[key] = (
                    time.monotonic() + self.failure_backoff_seconds
                )
            else:
                self._retry_after.pop(key, None)
            finally:
                self._inflight.discard(key)

        _track_background(asyncio.create_task(run()))


def render_retrieved_conversation_memories(
    items: list[RetrievedConversationMemory],
) -> str:
    if not items:
        return ""
    parts = [
        "[Relevant Earlier Conversation Memory]",
        "The following are compressed memories from older turns in THIS conversation. "
        "Use them only when relevant to the current request; newer raw conversation messages take precedence.",
    ]
    for index, item in enumerate(items, start=1):
        parts.append(f"\n[Conversation Memory {index}]\n{render_capsule(item.capsule)}")
    return "\n".join(parts)


def render_capsule(capsule: ConversationMemoryCapsule) -> str:
    lines = [f"summary={capsule.summary}"]
    if capsule.facts:
        lines.append("facts=" + " | ".join(capsule.facts))
    if capsule.decisions:
        lines.append("decisions=" + " | ".join(capsule.decisions))
    if capsule.open_tasks:
        lines.append("open_tasks=" + " | ".join(capsule.open_tasks))
    if capsule.entities:
        lines.append("entities=" + " | ".join(capsule.entities))
    return "\n".join(lines)


def _parse_capsule(
    raw: Any,
    *,
    user_id: int,
    conversation_id: int,
) -> ConversationMemoryCapsule | None:
    if not isinstance(raw, dict):
        return None
    try:
        item = ConversationMemoryCapsule(
            id=int(raw.get("id")),
            user_id=int(raw.get("userId")),
            conversation_id=int(raw.get("conversationId")),
            start_message_id=int(raw.get("startMessageId")),
            end_message_id=int(raw.get("endMessageId")),
            summary=" ".join(str(raw.get("summary", "")).split()),
            facts=tuple(_string_list(raw.get("facts"), 12, 500)),
            decisions=tuple(_string_list(raw.get("decisions"), 10, 500)),
            open_tasks=tuple(_string_list(raw.get("openTasks"), 10, 500)),
            entities=tuple(_string_list(raw.get("entities"), 16, 160)),
            keywords=tuple(_string_list(raw.get("keywords"), 20, 80)),
            importance=max(0.0, min(float(raw.get("importance", 0.5)), 1.0)),
            source_hash=str(raw.get("sourceHash", "")).strip().lower(),
            compaction_model=str(raw.get("compactionModel", "")).strip(),
            input_tokens=max(0, int(raw.get("inputTokens", 0) or 0)),
            output_tokens=max(0, int(raw.get("outputTokens", 0) or 0)),
            estimated_cost=(
                max(0.0, float(raw.get("estimatedCost")))
                if raw.get("estimatedCost") is not None
                else None
            ),
            created_at=_optional_string(raw.get("createdAt")),
            updated_at=_optional_string(raw.get("updatedAt")),
        )
    except (TypeError, ValueError):
        return None
    if (
        item.id <= 0
        or item.user_id != user_id
        or item.conversation_id != conversation_id
        or item.start_message_id <= 0
        or item.end_message_id < item.start_message_id
        or not item.summary
    ):
        return None
    return item


def _parse_compaction_json(content: str) -> dict[str, Any]:
    value = content.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
        value = re.sub(r"\s*```$", "", value)
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("conversation compactor response must be an object")
    summary = " ".join(str(parsed.get("summary", "")).split())
    if not summary:
        raise ValueError("conversation compactor summary is required")
    summary = _redact_sensitive(summary)[:1200]
    try:
        importance = float(parsed.get("importance", 0.5))
    except (TypeError, ValueError):
        importance = 0.5
    return {
        "summary": summary,
        "facts": _string_list(parsed.get("facts"), 12, 500, redact=True),
        "decisions": _string_list(parsed.get("decisions"), 10, 500, redact=True),
        "open_tasks": _string_list(parsed.get("open_tasks"), 10, 500, redact=True),
        "entities": _string_list(parsed.get("entities"), 16, 160, redact=True),
        "keywords": _string_list(parsed.get("keywords"), 20, 80, redact=True),
        "importance": max(0.0, min(importance, 1.0)),
    }


def _string_list(
    value: Any,
    max_items: int,
    max_chars: int,
    *,
    redact: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for raw in value:
        text = " ".join(str(raw).split()).strip()
        if redact:
            text = _redact_sensitive(text)
        if not text:
            continue
        result.append(text[:max_chars])
        if len(result) >= max_items:
            break
    return result


def _optional_string(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _bounded_safe_messages(
    messages: list[ConversationHistoryMessage],
    max_chars: int,
) -> list[ConversationHistoryMessage]:
    result: list[ConversationHistoryMessage] = []
    remaining = max_chars
    for item in messages:
        if remaining <= 0:
            break
        content = _redact_sensitive(" ".join(item.content.split()))
        if not content:
            continue
        limit = min(1600, remaining)
        content = content[:limit]
        remaining -= len(content)
        result.append(
            ConversationHistoryMessage(
                id=item.id,
                role=item.role,
                content=content,
                request_id=item.request_id,
            )
        )
    return result


_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key|jwt)\b\s*[:=]\s*[^\s,;]{4,}"
)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.S,
)


def _redact_sensitive(text: str) -> str:
    text = _PRIVATE_KEY_RE.sub("[redacted-private-key]", text)
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    return text


def _capsule_embedding_text(capsule: ConversationMemoryCapsule) -> str:
    return " ".join(
        [
            capsule.summary,
            *capsule.facts,
            *capsule.decisions,
            *capsule.open_tasks,
            *capsule.entities,
            *capsule.keywords,
        ]
    )


def _tokens(text: str) -> set[str]:
    normalized = text.lower()
    tokens = set(re.findall(r"[a-z0-9_]+", normalized))
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    tokens.update(cjk)
    if len(cjk) >= 2:
        tokens.update(cjk[index : index + 2] for index in range(len(cjk) - 1))
    return {item for item in tokens if item}


def _lexical_score(query: set[str], candidate: set[str]) -> float:
    if not query or not candidate:
        return 0.0
    overlap = len(query & candidate)
    return overlap / max(1, len(query))


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _is_broad_continuity_query(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    markers = (
        "之前", "前面", "刚才", "上次", "还记得", "继续", "接着",
        "earlier", "previous", "before", "continue", "remember",
    )
    return any(marker in normalized for marker in markers)
