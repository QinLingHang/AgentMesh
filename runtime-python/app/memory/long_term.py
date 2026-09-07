from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from app.models.contracts import ModelMessage, ModelRequest


MemoryCategory = Literal[
    "preference",
    "profile",
    "goal",
    "workflow",
    "fact",
    "other",
]

MemorySourceType = Literal[
    "explicit_user",
    "inferred_user",
]

MemoryWriteAction = Literal[
    "created",
    "updated",
    "unchanged",
    "preserved",
]


@dataclass(frozen=True, slots=True)
class MemoryDetection:
    should_extract: bool
    source_type: MemorySourceType = "inferred_user"
    reason: str = ""


@dataclass(frozen=True, slots=True)
class LongTermMemoryCandidate:
    category: MemoryCategory
    memory_key: str
    content: str
    source_type: MemorySourceType
    confidence: float


@dataclass(frozen=True, slots=True)
class MemoryWriteRecord:
    action: MemoryWriteAction
    memory_id: int | None
    memory_key: str
    category: str


@dataclass(frozen=True, slots=True)
class AutomaticMemoryWriteOutcome:
    status: Literal["completed", "skipped", "error"]
    reason: str
    candidate_count: int = 0
    records: tuple[MemoryWriteRecord, ...] = field(default_factory=tuple)
    extractor: str = "none"

    def trace_detail(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "candidateCount": self.candidate_count,
            "extractor": self.extractor,
            "writes": [
                {
                    "action": record.action,
                    "memoryId": record.memory_id,
                    "memoryKey": record.memory_key,
                    "category": record.category,
                }
                for record in self.records
            ],
        }


class LongTermMemorySink(Protocol):
    async def upsert(
        self,
        *,
        user_id: int,
        candidate: LongTermMemoryCandidate,
    ) -> MemoryWriteRecord:
        ...


class MemoryCandidateDetector:
    """Conservative pre-filter for user-global long-term memory writes.

    Only the *direct user task text* is inspected. Project Knowledge, RAG
    evidence, tool results, MCP results, citations and assistant output never
    enter this detector, which is the primary P3.2 source-boundary guarantee.
    """

    _explicit_patterns = (
        re.compile(r"^\s*(?:请|帮我)?记住(?:一下|[：:]|\s)", re.I),
        # Chinese “from now on” directives commonly omit punctuation, e.g.
        # “以后写 Go 代码时尽量和 Java 对比讲解”.  Do not require a
        # separator here; detect() still rejects question-shaped utterances.
        re.compile(r"^\s*(?:以后|今后|从现在起|从今以后|往后)", re.I),
        re.compile(r"^\s*(?:please\s+)?remember(?:\s+that|[,:\s])", re.I),
        re.compile(r"^\s*(?:from now on|going forward)(?:[,:\s]|$)", re.I),
    )

    _stable_markers = (
        "我喜欢",
        "我偏好",
        "我更喜欢",
        "我更倾向",
        "我习惯",
        "我通常",
        "我的目标是",
        "我的长期目标",
        "我的职业目标",
        "我的背景是",
        "我擅长",
        "i prefer",
        "i like",
        "i usually",
        "my goal is",
        "my long-term goal",
        "my background is",
        "i want you to",
    )

    _project_local_markers = (
        "本项目",
        "当前项目",
        "这个项目",
        "该项目",
        "project a",
        "project b",
        "this project",
        "current project",
    )

    _global_override_markers = (
        "所有项目",
        "任何项目",
        "跨项目",
        "每个项目",
        "all projects",
        "across projects",
        "every project",
    )

    _temporary_markers = (
        "今天",
        "明天",
        "这次",
        "本次",
        "当前任务",
        "临时",
        "暂时",
        "today",
        "tomorrow",
        "this time",
        "current task",
        "temporary",
    )

    _secret_patterns = (
        re.compile(r"(?i)\b(password|passwd|pwd)\b\s*[:=]"),
        re.compile(r"(?i)\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|secret)\b\s*[:=]"),
        re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{12,})\b"),
        re.compile(r"(?i)\b(ak|sk)[-_]?[A-Za-z0-9]{12,}\b"),
        re.compile(r"(?i)(密码|口令|密钥|令牌|token)\s*[：:=]\s*\S+"),
        re.compile(
            r"(?i)\b(?:otp|one[-_ ]?time(?:\s+(?:password|code))?|verification[-_ ]?code|credential(?:s)?)\b\s*[:=]\s*\S+"
        ),
        re.compile(r"(?i)(?:验证码|一次性(?:密码|口令|验证码)|凭据|认证信息)\s*[：:=]\s*\S+"),
    )

    def safety_rejection_reason(self, text: str) -> str:
        normalized = " ".join(text.strip().split())
        lower = normalized.lower()

        if any(pattern.search(normalized) for pattern in self._secret_patterns):
            return "sensitive_secret"

        if (
            any(marker in lower for marker in self._project_local_markers)
            and not any(marker in lower for marker in self._global_override_markers)
        ):
            return "project_scoped_statement"

        if any(marker in lower for marker in self._temporary_markers):
            return "temporary_statement"

        return ""

    def is_explicit_memory_request(self, text: str) -> bool:
        normalized = " ".join(text.strip().split())
        return any(
            pattern.search(normalized)
            for pattern in self._explicit_patterns
        )

    def detect(self, text: str) -> MemoryDetection:
        normalized = " ".join(text.strip().split())
        lower = normalized.lower()

        if len(normalized) < 4:
            return MemoryDetection(False, reason="too_short")

        rejection = self.safety_rejection_reason(normalized)
        if rejection:
            return MemoryDetection(False, reason=rejection)

        explicit = self.is_explicit_memory_request(normalized)

        if explicit:
            if normalized.endswith(("?", "？")) and "记住" not in normalized:
                return MemoryDetection(False, reason="question_not_memory")

            return MemoryDetection(
                True,
                source_type="explicit_user",
                reason="explicit_user_signal",
            )

        if any(marker in lower for marker in self._stable_markers):
            return MemoryDetection(
                True,
                source_type="inferred_user",
                reason="stable_user_signal",
            )

        return MemoryDetection(False, reason="no_stable_memory_signal")


class RuleBasedMemoryExtractor:
    _prefix_patterns = (
        re.compile(r"^\s*(?:请|帮我)?记住(?:一下|：|:)?\s*", re.I),
        re.compile(r"^\s*(?:以后|今后|从现在起|从今以后|往后)[，,:：\s]*", re.I),
        re.compile(r"^\s*(?:please\s+)?remember(?:\s+that)?[,:\s]*", re.I),
        re.compile(r"^\s*(?:from now on|going forward)[,:\s]*", re.I),
    )

    def extract(
        self,
        *,
        text: str,
        source_type: MemorySourceType,
    ) -> list[LongTermMemoryCandidate]:
        content = " ".join(text.strip().split())

        for pattern in self._prefix_patterns:
            content = pattern.sub("", content, count=1).strip()

        content = content.strip(" ，,。.!！;；")
        if not content:
            return []

        if len(content) > 1000:
            content = content[:1000].rstrip()

        category, memory_key = self._classify(content)

        confidence = 0.98 if source_type == "explicit_user" else 0.78

        return [
            LongTermMemoryCandidate(
                category=category,
                memory_key=memory_key,
                content=content,
                source_type=source_type,
                confidence=confidence,
            )
        ]

    def _classify(self, content: str) -> tuple[MemoryCategory, str]:
        lower = content.lower()

        if any(token in lower for token in ("中文", "英文", "language", "语言")):
            return "preference", "preference.response_language"

        if (
            any(token in lower for token in ("java", "go", "python", "代码", "语法"))
            and any(token in lower for token in ("对比", "讲解", "解释", "compare", "explain"))
        ):
            return "preference", "preference.coding.explanation_style"

        if (
            any(token in lower for token in ("完整代码", "完整文件", "直接替换", "copy", "复制粘贴"))
        ):
            return "preference", "preference.coding.delivery_style"

        if any(token in lower for token in ("agent 开发", "agent开发", "后端开发", "职业目标", "岗位", "career")):
            return "goal", "goal.career.target_role"

        if any(token in lower for token in ("界面", "ui", "视觉", "布局")):
            return "preference", "preference.ui.style"

        if any(token in lower for token in ("习惯", "通常", "workflow", "流程")):
            category: MemoryCategory = "workflow"
        elif any(token in lower for token in ("目标", "goal")):
            category = "goal"
        elif any(token in lower for token in ("喜欢", "偏好", "倾向", "prefer", "like")):
            category = "preference"
        elif any(token in lower for token in ("背景", "我是", "my background")):
            category = "profile"
        else:
            category = "other"

        digest = hashlib.sha256(
            self._canonicalize(content).encode("utf-8")
        ).hexdigest()[:16]

        return category, f"auto.{category}.{digest}"

    @staticmethod
    def _canonicalize(value: str) -> str:
        value = value.lower().strip()
        value = re.sub(r"\s+", " ", value)
        value = re.sub(r"[，。！？,.!?;；:：\"'“”‘’]", "", value)
        return value


class ModelBackedMemoryExtractor:
    _valid_categories = {
        "preference",
        "profile",
        "goal",
        "workflow",
        "fact",
        "other",
    }
    _key_pattern = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")

    def __init__(
        self,
        model_gateway: Any,
        *,
        model_name: str,
        max_items: int = 3,
    ) -> None:
        self.model_gateway = model_gateway
        self.model_name = model_name
        self.max_items = max(1, min(max_items, 5))

    async def extract(
        self,
        *,
        text: str,
    ) -> list[LongTermMemoryCandidate]:
        response = await self.model_gateway.generate(
            ModelRequest(
                model=self.model_name,
                temperature=0.0,
                max_tokens=500,
                messages=[
                    ModelMessage(
                        role="system",
                        content=(
                            "You extract durable user-global long-term memories from ONLY the direct user message. "
                            "Never use project knowledge, RAG evidence, tool/MCP output, citations, secrets, temporary facts, "
                            "or project-local facts. Return strict JSON only: "
                            '{"items":[{"category":"preference|profile|goal|workflow|fact|other",'
                            '"memory_key":"stable.lowercase.key","content":"durable fact",'
                            '"confidence":0.0}]}.'
                            " Use an empty items array when nothing durable should be remembered. "
                            "memory_key must be stable across paraphrases, concise, lowercase, and use dots/underscores only. "
                            f"Return at most {self.max_items} items."
                        ),
                    ),
                    ModelMessage(
                        role="user",
                        content=text.strip(),
                    ),
                ],
            )
        )

        payload = self._parse_json(response.content)
        raw_items = payload.get("items", [])
        if not isinstance(raw_items, list):
            # A malformed model payload must be distinguishable from a valid
            # “no durable memory” response (items=[]).  Raising here lets the
            # writer's existing exception path invoke the deterministic rule
            # fallback instead of silently dropping a valid memory candidate.
            raise ValueError("memory extractor items must be a list")

        candidates: list[LongTermMemoryCandidate] = []
        for item in raw_items[: self.max_items]:
            if not isinstance(item, dict):
                continue

            category = str(item.get("category", "")).strip().lower()
            memory_key = str(item.get("memory_key", "")).strip().lower()
            content = " ".join(str(item.get("content", "")).strip().split())

            if category not in self._valid_categories:
                continue
            if not self._key_pattern.fullmatch(memory_key):
                continue
            if not content or len(content) > 1000:
                continue

            try:
                confidence = float(item.get("confidence", 0.75))
            except (TypeError, ValueError):
                confidence = 0.75

            confidence = max(0.0, min(confidence, 1.0))

            candidates.append(
                LongTermMemoryCandidate(
                    category=category,  # type: ignore[arg-type]
                    memory_key=memory_key,
                    content=content,
                    source_type="inferred_user",
                    confidence=confidence,
                )
            )

        return candidates

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        value = content.strip()
        if value.startswith("```"):
            value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
            value = re.sub(r"\s*```$", "", value)

        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("memory extractor response must be an object")
        return parsed


class ControlPlaneLongTermMemorySink:
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

    async def upsert(
        self,
        *,
        user_id: int,
        candidate: LongTermMemoryCandidate,
    ) -> MemoryWriteRecord:
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            trust_env=False,
        ) as client:
            response = await client.post(
                f"{self.base_url}/internal/v1/users/{user_id}/memories/upsert",
                headers={
                    "X-Internal-Token": self.internal_token,
                },
                json={
                    "category": candidate.category,
                    "memoryKey": candidate.memory_key,
                    "content": candidate.content,
                    "sourceType": candidate.source_type,
                    "confidence": candidate.confidence,
                },
            )
            response.raise_for_status()
            payload = response.json()

        data = payload.get("data", payload)
        memory = data.get("memory") or {}
        action = str(data.get("action", "updated")).strip().lower()
        if action not in {"created", "updated", "unchanged", "preserved"}:
            action = "updated"

        memory_id = memory.get("id")
        return MemoryWriteRecord(
            action=action,  # type: ignore[arg-type]
            memory_id=int(memory_id) if memory_id is not None else None,
            memory_key=str(memory.get("memoryKey", candidate.memory_key)),
            category=str(memory.get("category", candidate.category)),
        )


class AutomaticLongTermMemoryWriter:
    """P3.2 automatic write orchestrator.

    This component intentionally has no retrieval or prompt-injection behavior.
    It only turns direct user text into durable user-global memory candidates and
    sends them to the Go control-plane ownership boundary.
    """

    def __init__(
        self,
        *,
        sink: LongTermMemorySink,
        detector: MemoryCandidateDetector | None = None,
        rule_extractor: RuleBasedMemoryExtractor | None = None,
        model_extractor: ModelBackedMemoryExtractor | None = None,
        enabled: bool = True,
    ) -> None:
        self.sink = sink
        self.detector = detector or MemoryCandidateDetector()
        self.rule_extractor = rule_extractor or RuleBasedMemoryExtractor()
        self.model_extractor = model_extractor
        self.enabled = enabled

    async def process(
        self,
        *,
        user_id: int,
        text: str,
    ) -> AutomaticMemoryWriteOutcome:
        if not self.enabled:
            return AutomaticMemoryWriteOutcome(
                status="skipped",
                reason="disabled",
            )

        detection = self.detector.detect(text)
        if not detection.should_extract:
            return AutomaticMemoryWriteOutcome(
                status="skipped",
                reason=detection.reason,
            )

        candidates: list[LongTermMemoryCandidate]
        extractor = "rule"

        if detection.source_type == "explicit_user":
            candidates = self.rule_extractor.extract(
                text=text,
                source_type="explicit_user",
            )
        elif self.model_extractor is not None:
            try:
                candidates = await self.model_extractor.extract(text=text)
                extractor = "model"
            except Exception:
                candidates = self.rule_extractor.extract(
                    text=text,
                    source_type="inferred_user",
                )
                extractor = "rule_fallback"
        else:
            candidates = self.rule_extractor.extract(
                text=text,
                source_type="inferred_user",
            )

        safe_candidates: list[LongTermMemoryCandidate] = []
        for candidate in candidates:
            rejection = self.detector.safety_rejection_reason(
                candidate.content
            )
            if rejection:
                continue

            if candidate.memory_key.startswith(
                (
                    "project.",
                    "knowledge.",
                    "rag.",
                    "tool.",
                    "mcp.",
                    "secret.",
                )
            ):
                continue

            safe_candidates.append(candidate)

        candidates = safe_candidates

        if not candidates:
            return AutomaticMemoryWriteOutcome(
                status="skipped",
                reason="no_valid_candidate",
                extractor=extractor,
            )

        records: list[MemoryWriteRecord] = []
        try:
            for candidate in candidates:
                records.append(
                    await self.sink.upsert(
                        user_id=user_id,
                        candidate=candidate,
                    )
                )
        except Exception as exc:
            return AutomaticMemoryWriteOutcome(
                status="error",
                reason=f"control_plane_write_failed:{type(exc).__name__}",
                candidate_count=len(candidates),
                records=tuple(records),
                extractor=extractor,
            )

        return AutomaticMemoryWriteOutcome(
            status="completed",
            reason="memory_written",
            candidate_count=len(candidates),
            records=tuple(records),
            extractor=extractor,
        )
