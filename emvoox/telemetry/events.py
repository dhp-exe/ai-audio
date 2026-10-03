"""Vendor limit events (429 / 402 / quota) recorded by the adapters for the Costs page."""

from __future__ import annotations

from datetime import UTC, datetime


def record_event(provider: str, model: str, kind: str, *, status: int | None = None, quota_id: str | None = None,
                 quota_value: int | str | None = None, retry_after_s: float | None = None, message: str = "") -> None:
    """Append a vendor limit event. kind: rate_limit | quota_daily | quota_monthly | payment_required | error."""
    try:
        from emvoox.repositories import get_repositories

        get_repositories().telemetry.record_event({
            "at": datetime.now(UTC).isoformat(timespec="seconds"), "provider": provider, "model": model, "kind": kind,
            "status": status, "quota_id": quota_id, "quota_value": quota_value, "retry_after_s": retry_after_s,
            "message": message[:300]})
    except Exception:  # noqa: BLE001 - monitoring must never break a render
        pass
