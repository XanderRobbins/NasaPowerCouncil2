"""Asset information models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class AssetClass(str, Enum):
    EQUITY = "equity"
    ETF = "etf"
    CRYPTO = "crypto"
    FOREX = "forex"
    FUTURES = "futures"
    INDEX = "index"
    OPTION = "option"
    UNKNOWN = "unknown"


class AssetInfo(BaseModel):
    """General descriptive information about a financial asset."""

    symbol: str
    name: str = ""
    asset_class: AssetClass = AssetClass.UNKNOWN
    exchange: str = ""
    currency: str = ""
    country: str = ""
    sector: str = ""
    industry: str = ""
    description: str = ""
    market_cap: float | None = None
    employees: int | None = None
    website: str = ""
    #: Source-specific extra fields passed through transparently.
    extra: dict[str, Any] = {}
    source: str = ""
