"""Tenacity retry decorators with exponential backoff + jitter."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from findata.exceptions import SourceRateLimitError, SourceUnavailableError

logger = logging.getLogger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient errors that should be retried."""
    if isinstance(exc, SourceRateLimitError | SourceUnavailableError):
        return True
    if isinstance(exc, httpx.TimeoutException | httpx.NetworkError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


def _log_retry(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "Retrying %s (attempt %d): %s",
        retry_state.fn.__name__ if retry_state.fn else "unknown",
        retry_state.attempt_number,
        exc,
    )


#: Standard retry decorator: up to 4 attempts, exp backoff 1–30s, ±2s jitter.
http_retry = retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=1, max=30, jitter=2),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
