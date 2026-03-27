"""OHLCV price bar model with validation."""

from __future__ import annotations

from datetime import date, datetime
from typing import Union

from pydantic import BaseModel, Field, field_validator, model_validator


class PriceBar(BaseModel):
    """A single OHLCV bar (daily, intraday, or tick-level)."""

    timestamp: Union[datetime, date]
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    adjusted_close: float | None = Field(default=None, gt=0)
    source: str = ""

    @model_validator(mode="after")
    def _ohlcv_relationships(self) -> "PriceBar":
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) < low ({self.low})")
        if self.high < self.open:
            raise ValueError(f"high ({self.high}) < open ({self.open})")
        if self.high < self.close:
            raise ValueError(f"high ({self.high}) < close ({self.close})")
        if self.low > self.open:
            raise ValueError(f"low ({self.low}) > open ({self.open})")
        if self.low > self.close:
            raise ValueError(f"low ({self.low}) > close ({self.close})")
        return self
