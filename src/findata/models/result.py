"""DataResult — enriched response envelope carrying provenance and quality metadata."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import pandas as pd
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass


class SourceContribution(BaseModel):
    """Records which source contributed data points and how many."""

    source: str
    rows: int
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    from_cache: bool = False


class DataResult:
    """Enriched wrapper around a pandas DataFrame with provenance metadata.

    Attributes
    ----------
    df:
        The underlying pandas DataFrame.
    symbol:
        The requested symbol.
    sources:
        Which data sources contributed rows and when.
    validated:
        Whether the data passed quality validation.
    warnings:
        Non-fatal quality issues detected during validation.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        *,
        symbol: str,
        sources: list[SourceContribution] | None = None,
        validated: bool = False,
        warnings: list[str] | None = None,
    ) -> None:
        self.df = df
        self.symbol = symbol
        self.sources: list[SourceContribution] = sources or []
        self.validated = validated
        self.warnings: list[str] = warnings or []

    # ── Convenience accessors ─────────────────────────────────────────────────

    def to_pandas(self) -> pd.DataFrame:
        """Return the underlying pandas DataFrame."""
        return self.df

    def to_polars(self) -> Any:
        """Return a Polars DataFrame (requires findata[polars])."""
        try:
            import polars as pl  # type: ignore[import-untyped]
        except ImportError:
            from findata.exceptions import MissingDependencyError

            raise MissingDependencyError("polars", "polars") from None
        return pl.from_pandas(self.df)

    @property
    def primary_source(self) -> str:
        """Name of the source that contributed the most rows."""
        if not self.sources:
            return "unknown"
        return max(self.sources, key=lambda s: s.rows).source

    @property
    def freshness(self) -> datetime | None:
        """Earliest fetch timestamp across all contributing sources."""
        if not self.sources:
            return None
        return min(s.fetched_at for s in self.sources)

    # ── Magic ─────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        src_names = ", ".join(s.source for s in self.sources)
        return (
            f"DataResult(symbol={self.symbol!r}, rows={len(self.df)}, "
            f"sources=[{src_names}], validated={self.validated})"
        )

    def __len__(self) -> int:
        return len(self.df)

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to the underlying DataFrame."""
        return getattr(self.df, name)
