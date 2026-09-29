from __future__ import annotations

import asyncio
import hashlib
import math
import re

from typing import Protocol

import httpx

from openai import AsyncOpenAI


class EmbeddingProvider(
    Protocol
):
    dimension: int

    async def embed(
        self,
        texts: list[str],
    ) -> list[
        list[float]
    ]:
        ...


# =========================================================
# Deterministic Local Embedding
# =========================================================


class HashEmbeddingProvider:
    """
    Deterministic local embedding baseline.

    作用不是替代真正的语义 Embedding Model。

    它主要用于：

        - 本地开发
        - 单元测试
        - 无 API Key 环境
        - Milvus 全链路验证

    与随机向量不同，它会根据 token
    稳定映射到向量空间，因此相同或部分重叠的
    文本仍然具有可检索性。
    """

    def __init__(
        self,
        *,
        dimension: int = 256,
    ) -> None:

        if dimension <= 1:
            raise ValueError(
                "embedding dimension must be > 1"
            )

        self.dimension = (
            dimension
        )

    async def embed(
        self,
        texts: list[str],
    ) -> list[
        list[float]
    ]:

        return [
            self._embed_one(
                text
            )
            for text
            in texts
        ]

    def _embed_one(
        self,
        text: str,
    ) -> list[float]:

        vector = [
            0.0
            for _ in range(
                self.dimension
            )
        ]

        tokens = (
            self._tokens(
                text
            )
        )

        if not tokens:
            return vector

        for token in tokens:
            digest = (
                hashlib.blake2b(
                    token.encode(
                        "utf-8"
                    ),
                    digest_size=8,
                ).digest()
            )

            index = (
                int.from_bytes(
                    digest[
                        :4
                    ],
                    "big",
                )
                % self.dimension
            )

            sign = (
                1.0
                if (
                    digest[4]
                    % 2
                    == 0
                )
                else -1.0
            )

            vector[
                index
            ] += sign

        norm = math.sqrt(
            sum(
                value * value
                for value
                in vector
            )
        )

        if norm == 0:
            return vector

        return [
            value / norm
            for value
            in vector
        ]

    @staticmethod
    def _tokens(
        text: str,
    ) -> list[str]:
        return re.findall(
            (
                r"[a-z0-9_]+"
                r"|"
                r"[\u4e00-\u9fff]"
            ),
            text.lower(),
        )


# =========================================================
# OpenAI-Compatible Embedding
# =========================================================


class OpenAICompatibleEmbeddingProvider:
    """
    OpenAI-compatible embedding provider.

    可用于：

        DashScope
        OpenAI
        其他兼容 /embeddings 的 Provider
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dimension: int,
        trust_env: bool = True,
        timeout_seconds: float = 20.0,
        sdk_max_retries: int | None = None,
    ) -> None:

        if not api_key:
            raise ValueError(
                "embedding api key is required"
            )

        if dimension <= 1:
            raise ValueError(
                "embedding dimension must be > 1"
            )

        if timeout_seconds <= 0:
            raise ValueError(
                "embedding timeout_seconds must be > 0"
            )

        if sdk_max_retries is not None and sdk_max_retries < 0:
            raise ValueError(
                "embedding sdk_max_retries must be >= 0"
            )

        self.dimension = (
            dimension
        )

        self.timeout_seconds = (
            float(timeout_seconds)
        )

        self.sdk_max_retries = (
            sdk_max_retries
        )

        self.model = (
            model
        )

        self._http_client = (
            httpx.AsyncClient(
                trust_env=(
                    trust_env
                ),
                timeout=httpx.Timeout(
                    self.timeout_seconds
                ),
            )
        )

        client_kwargs = {
            "api_key": api_key,
            "base_url": base_url,
            "http_client": (
                self._http_client
            ),
            "timeout": (
                self.timeout_seconds
            ),
        }

        if (
            self.sdk_max_retries
            is not None
        ):
            client_kwargs[
                "max_retries"
            ] = (
                self.sdk_max_retries
            )

        self._client = (
            AsyncOpenAI(
                **client_kwargs
            )
        )

    async def embed(
        self,
        texts: list[str],
    ) -> list[
        list[float]
    ]:

        if not texts:
            return []

        request = (
            self
            ._client
            .embeddings
            .create(
                model=(
                    self.model
                ),
                input=texts,
                dimensions=(
                    self.dimension
                ),
            )
        )

        try:
            response = (
                await asyncio.wait_for(
                    request,
                    timeout=(
                        self.timeout_seconds
                        + 1.0
                    ),
                )
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                (
                    "embedding request timed out "
                    f"after {self.timeout_seconds:.1f}s"
                )
            ) from exc

        ordered = sorted(
            response.data,
            key=lambda item:
                item.index,
        )

        vectors = [
            list(
                item.embedding
            )
            for item
            in ordered
        ]

        for vector in vectors:
            if (
                len(vector)
                != self.dimension
            ):
                raise RuntimeError(
                    (
                        "embedding dimension "
                        "mismatch: expected "
                        f"{self.dimension}, "
                        f"got {len(vector)}"
                    )
                )

        return vectors

    async def aclose(
        self,
    ) -> None:
        await (
            self
            ._http_client
            .aclose()
        )