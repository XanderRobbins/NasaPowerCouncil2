"""DataSource metadata model."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SupportedDataType(str, Enum):
    PRICES = "prices"
    INFO = "info"
    FOREX = "forex"
    CRYPTO = "crypto"
    FUNDAMENTALS = "fundamentals"
    OPTIONS = "options"


class DataSourceMeta(BaseModel):
    name: str
    description: str = ""
    supported_types: list[SupportedDataType] = Field(default_factory=list)
    requires_api_key: bool = False
    rate_limit_per_minute: float | None = None
    rate_limit_per_day: float | None = None
    risk_tier: int = Field(default=2, ge=1, le=3)
    tos_url: str = ""
