"""Exponential-ish backoff for notification delivery retries."""

from __future__ import annotations

# Seconds after each failed delivery attempt (1-based failure count).
_BACKOFF_SEQUENCE = (
    60,  # 1 minute
    300,  # 5 minutes
    900,  # 15 minutes
    3600,  # 1 hour
    21600,  # 6 hours
)
_MAX_BACKOFF_SECONDS = 86400  # 24 hours cap


def compute_notification_backoff_seconds(failure_count: int) -> int:
    """Return delay before next retry.

    ``failure_count`` is the number of failed delivery attempts so far (>= 1).
    First failure → 1 minute; then 5m, 15m, 1h, 6h; then cap at 24h.
    """
    if failure_count < 1:
        failure_count = 1
    idx = failure_count - 1
    if idx < len(_BACKOFF_SEQUENCE):
        return _BACKOFF_SEQUENCE[idx]
    return _MAX_BACKOFF_SECONDS


__all__ = ["compute_notification_backoff_seconds", "_MAX_BACKOFF_SECONDS"]
