"""Lightweight request-scoped model and constraint contracts.

This module intentionally has no Runtime, Tool, MCP, RAG, or Agent imports so
preflight routing can validate request metadata without loading the execution
stack. ``app.schemas`` re-exports these contracts for backward-compatible
imports used by the rest of the Runtime.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class TaskConstraints(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    max_latency_ms: int = Field(default=8000, alias="maxLatencyMs")
    max_cost: float = Field(default=0.15, alias="maxCost")
    min_quality: float = Field(default=0.8, alias="minQuality")
    retry_on_worker_loss: bool = Field(default=False, alias="retryOnWorkerLoss")


class ProjectModelRuntime(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    service_id: int | None = Field(default=None, alias="serviceId")
    service_name: str | None = Field(default=None, alias="serviceName")
    provider: str = "openai-compatible"
    base_url: str = Field(alias="baseUrl")
    model_name: str = Field(alias="modelName")
    vision_model_name: str | None = Field(default=None, alias="visionModelName")
    api_key: SecretStr = Field(alias="apiKey")
    auto_route: bool = Field(default=True, alias="autoRoute")
    is_default: bool = Field(default=False, alias="isDefault")


class ModelSelection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mode: Literal["auto", "manual"] = "auto"
    service_id: int | None = Field(default=None, alias="serviceId")
