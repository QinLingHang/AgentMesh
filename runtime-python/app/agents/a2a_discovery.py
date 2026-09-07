from __future__ import annotations

import asyncio
import time

from dataclasses import (
    dataclass,
    replace,
)

import httpx

from a2a.client import (
    A2ACardResolver,
)

from app.schemas import (
    AgentCapabilityProfile,
    AgentProfile,
)


class A2ACapabilityDiscoveryError(
    RuntimeError
):
    """Raised when an A2A Agent Card cannot be discovered."""


@dataclass(
    frozen=True,
    slots=True,
)
class A2ADiscoveryResult:
    endpoint: str

    remote_name: str
    remote_version: str

    capabilities: tuple[
        str,
        ...
    ]

    skill_count: int

    cache_hit: bool = False

    added_capabilities: tuple[
        str,
        ...
    ] = ()


@dataclass(
    frozen=True,
    slots=True,
)
class _CacheEntry:
    expires_at: float

    result: A2ADiscoveryResult


class A2ACapabilityDiscovery:
    """
    Discover A2A Agent capabilities from Agent Card.

    Agent Card
        ↓
    skills
        ↓
    capability IDs
        ↓
    AgentProfile.capabilities
        ↓
    AgentCapabilityProfile

    Important:

    Agent Card tells us:
        "what the remote agent claims it can do"

    Runtime feedback tells us:
        "how well it actually performs"

    Therefore discovery never overwrites historical
    capability metrics.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        trust_env: bool = False,
        cache_ttl_seconds: float = 300.0,
    ) -> None:

        if timeout_seconds <= 0:
            raise ValueError(
                (
                    "A2A discovery timeout "
                    "must be > 0"
                )
            )

        if cache_ttl_seconds < 0:
            raise ValueError(
                (
                    "A2A discovery cache TTL "
                    "must be >= 0"
                )
            )

        self.timeout_seconds = (
            timeout_seconds
        )

        self.trust_env = (
            trust_env
        )

        self.cache_ttl_seconds = (
            cache_ttl_seconds
        )

        self._cache: dict[
            str,
            _CacheEntry,
        ] = {}

        # 防止并发 Task 在缓存 miss 时
        # 同时对同一个远程 Agent 发 Discovery。
        #
        # 当前先使用一个简单锁。
        # 后续 Agent 数量很大时可以演进成
        # endpoint-scoped lock。
        self._lock = (
            asyncio.Lock()
        )

    # =====================================================
    # Public Discovery
    # =====================================================

    async def discover(
        self,
        agent: AgentProfile,
    ) -> A2ADiscoveryResult:

        endpoint = (
            agent.endpoint
            .strip()
            .rstrip("/")
        )

        if not endpoint:
            raise (
                A2ACapabilityDiscoveryError(
                    (
                        "A2A agent endpoint "
                        "must not be empty"
                    )
                )
            )

        if (
            agent.protocol
            .strip()
            .lower()
            != "a2a"
        ):
            raise (
                A2ACapabilityDiscoveryError(
                    (
                        "capability discovery "
                        "requires protocol=a2a"
                    )
                )
            )

        cached = (
            self._get_cached(
                endpoint
            )
        )

        if cached is not None:
            return cached

        async with self._lock:

            # Double check。
            #
            # Request A 获取锁完成 Discovery 后，
            # Request B 再拿到锁时不能继续请求一次。
            cached = (
                self._get_cached(
                    endpoint
                )
            )

            if cached is not None:
                return cached

            result = (
                await self
                ._fetch_agent_card(
                    endpoint
                )
            )

            self._put_cache(
                endpoint,
                result,
            )

            return result

    # =====================================================
    # Hydrate AgentProfile
    # =====================================================

    async def hydrate(
        self,
        agent: AgentProfile,
    ) -> A2ADiscoveryResult:
        """
        Merge remote Agent Card skills into AgentProfile.

        Existing capabilities:
            preserved

        Existing Capability Profiles:
            preserved

        Newly discovered capabilities:
            create baseline CapabilityProfile
        """

        result = (
            await self.discover(
                agent
            )
        )

        existing_capabilities = {
            self._normalize_capability(
                item
            )
            for item
            in agent.capabilities
            if item.strip()
        }

        added: list[str] = []

        for capability in (
            result.capabilities
        ):
            if (
                capability
                in existing_capabilities
            ):
                continue

            agent.capabilities.append(
                capability
            )

            existing_capabilities.add(
                capability
            )

            added.append(
                capability
            )

        # =================================================
        # Existing historical profiles
        #
        # These have Runtime feedback and therefore
        # must NOT be overwritten by Agent Card discovery.
        # =================================================

        profile_capabilities = {
            self._normalize_capability(
                profile.capability
            )
            for profile
            in agent.capability_profiles
        }

        for capability in (
            result.capabilities
        ):
            if (
                capability
                in profile_capabilities
            ):
                continue

            # =============================================
            # New skill starts with Agent-level baseline.
            #
            # 后续 Runtime Feedback 会继续通过 EWMA
            # 更新这些真实指标。
            # =============================================

            agent.capability_profiles.append(
                AgentCapabilityProfile(
                    capability=(
                        capability
                    ),

                    quality_score=(
                        agent
                        .quality_score
                    ),

                    avg_latency_ms=(
                        agent
                        .avg_latency_ms
                    ),

                    avg_cost=(
                        agent
                        .avg_cost
                    ),

                    success_rate=(
                        agent
                        .success_rate
                    ),

                    failure_rate=(
                        agent
                        .failure_rate
                    ),

                    sample_count=0,
                )
            )

            profile_capabilities.add(
                capability
            )

        return replace(
            result,
            added_capabilities=(
                tuple(
                    added
                )
            ),
        )

    # =====================================================
    # Actual Agent Card Request
    # =====================================================

    async def _fetch_agent_card(
        self,
        endpoint: str,
    ) -> A2ADiscoveryResult:

        try:
            async with httpx.AsyncClient(
                timeout=(
                    self.timeout_seconds
                ),
                trust_env=(
                    self.trust_env
                ),
            ) as client:

                resolver = (
                    A2ACardResolver(
                        httpx_client=(
                            client
                        ),
                        base_url=(
                            endpoint
                        ),
                    )
                )

                card = (
                    await resolver
                    .get_agent_card()
                )

        except Exception as exc:
            raise (
                A2ACapabilityDiscoveryError(
                    (
                        "failed to discover "
                        "A2A Agent Card from "
                        f"{endpoint}: {exc}"
                    )
                )
            ) from exc

        remote_name = str(
            getattr(
                card,
                "name",
                "",
            )
        ).strip()

        remote_version = str(
            getattr(
                card,
                "version",
                "",
            )
        ).strip()

        skills = list(
            getattr(
                card,
                "skills",
                [],
            )
            or []
        )

        capabilities: list[
            str
        ] = []

        seen: set[str] = set()

        for skill in skills:

            raw_capability = str(
                getattr(
                    skill,
                    "id",
                    "",
                )
                or getattr(
                    skill,
                    "name",
                    "",
                )
            )

            capability = (
                self
                ._normalize_capability(
                    raw_capability
                )
            )

            if not capability:
                continue

            if capability in seen:
                continue

            seen.add(
                capability
            )

            capabilities.append(
                capability
            )

        return A2ADiscoveryResult(
            endpoint=(
                endpoint
            ),

            remote_name=(
                remote_name
            ),

            remote_version=(
                remote_version
            ),

            capabilities=(
                tuple(
                    capabilities
                )
            ),

            skill_count=(
                len(skills)
            ),

            cache_hit=False,
        )

    # =====================================================
    # Cache
    # =====================================================

    def _get_cached(
        self,
        endpoint: str,
    ) -> A2ADiscoveryResult | None:

        if (
            self.cache_ttl_seconds
            <= 0
        ):
            return None

        entry = (
            self._cache.get(
                endpoint
            )
        )

        if entry is None:
            return None

        now = (
            time.monotonic()
        )

        if (
            now
            >= entry.expires_at
        ):
            self._cache.pop(
                endpoint,
                None,
            )

            return None

        return replace(
            entry.result,
            cache_hit=True,
            added_capabilities=(),
        )

    def _put_cache(
        self,
        endpoint: str,
        result: A2ADiscoveryResult,
    ) -> None:

        if (
            self.cache_ttl_seconds
            <= 0
        ):
            return

        self._cache[
            endpoint
        ] = _CacheEntry(
            expires_at=(
                time.monotonic()
                + self
                .cache_ttl_seconds
            ),

            result=(
                result
            ),
        )

    def invalidate(
        self,
        endpoint: str | None = None,
    ) -> None:
        """
        Agent Registry update 后可以主动清缓存。

        当前 v1.9.3 先提供能力，
        后续 Go Control Plane Registry Update
        再调用它。
        """

        if endpoint is None:
            self._cache.clear()
            return

        normalized = (
            endpoint
            .strip()
            .rstrip("/")
        )

        self._cache.pop(
            normalized,
            None,
        )

    # =====================================================
    # Capability ID
    # =====================================================

    @staticmethod
    def _normalize_capability(
        value: str,
    ) -> str:

        return "_".join(
            value
            .strip()
            .lower()
            .split()
        )