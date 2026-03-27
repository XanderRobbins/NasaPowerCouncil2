"""Rich, informative exception hierarchy for findata."""

from __future__ import annotations


class FindataError(Exception):
    """Base class for all findata exceptions."""


# ── Source errors ─────────────────────────────────────────────────────────────


class SourceError(FindataError):
    """A data source encountered an error."""

    def __init__(self, source: str, message: str, *, status_code: int | None = None) -> None:
        self.source = source
        self.status_code = status_code
        super().__init__(f"[{source}] {message}" + (f" (HTTP {status_code})" if status_code else ""))


class SourceUnavailableError(SourceError):
    """Source is temporarily unavailable (circuit breaker open or network error)."""


class SourceRateLimitError(SourceError):
    """Source rate limit exceeded (HTTP 429)."""

    def __init__(self, source: str, *, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        msg = "Rate limit exceeded"
        if retry_after:
            msg += f"; retry after {retry_after:.0f}s"
        super().__init__(source, msg, status_code=429)


class SourceAuthError(SourceError):
    """Authentication failed (HTTP 401/403). Check your API key."""


class SymbolNotFoundError(SourceError):
    """Symbol not found on this source (HTTP 404 or empty response)."""

    def __init__(self, source: str, symbol: str) -> None:
        self.symbol = symbol
        super().__init__(source, f"Symbol not found: {symbol!r}", status_code=404)


class AllSourcesFailedError(FindataError):
    """All configured sources failed to return data."""

    def __init__(self, symbol: str, errors: dict[str, Exception]) -> None:
        self.symbol = symbol
        self.errors = errors
        details = "; ".join(f"{src}: {err}" for src, err in errors.items())
        super().__init__(f"All sources failed for {symbol!r}: {details}")


# ── Validation errors ─────────────────────────────────────────────────────────


class DataValidationError(FindataError):
    """Data failed quality validation."""

    def __init__(self, message: str, *, source: str | None = None, field: str | None = None) -> None:
        self.source = source
        self.field = field
        prefix = f"[{source}] " if source else ""
        suffix = f" (field: {field})" if field else ""
        super().__init__(f"{prefix}Validation error{suffix}: {message}")


# ── Configuration errors ──────────────────────────────────────────────────────


class ConfigurationError(FindataError):
    """Invalid library configuration."""


class MissingDependencyError(FindataError):
    """An optional dependency is required for this feature."""

    def __init__(self, package: str, extra: str) -> None:
        self.package = package
        self.extra = extra
        super().__init__(
            f"{package!r} is required for this feature. "
            f"Install it with: pip install findata[{extra}]"
        )
