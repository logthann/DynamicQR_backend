"""Tests for redirect URL construction behavior."""

from datetime import UTC, datetime, timedelta

from app.core.metrics import get_metrics_collector, reset_metrics_collector
from app.schemas.redirect import QRCodeStatus, RedirectQRCode
from app.services.redirect_service import build_redirect_url


def _build_qr(destination_url: str, **kwargs: str | None) -> RedirectQRCode:
    return RedirectQRCode(
        id=1,
        short_code="abc123",
        destination_url=destination_url,
        status=QRCodeStatus.active,
        deleted_at=None,
        ga_measurement_id=None,
        utm_source=kwargs.get("utm_source"),
        utm_medium=kwargs.get("utm_medium"),
        utm_campaign=kwargs.get("utm_campaign"),
    )


def test_build_redirect_url_appends_utm_params() -> None:
    qr = _build_qr(
        "https://example.com/landing",
        utm_source="newsletter",
        utm_medium="email",
        utm_campaign="black-friday",
    )

    result = build_redirect_url(qr)

    assert result == (
        "https://example.com/landing"
        "?utm_source=newsletter&utm_medium=email&utm_campaign=black-friday"
    )


def test_build_redirect_url_preserves_existing_query_and_overrides_utm() -> None:
    qr = _build_qr(
        "https://example.com/landing?ref=abc&utm_source=old",
        utm_source="new-source",
        utm_medium="social",
    )

    result = build_redirect_url(qr)

    assert result == "https://example.com/landing?ref=abc&utm_source=new-source&utm_medium=social"


def test_build_redirect_url_keeps_original_when_no_utm_values() -> None:
    qr = _build_qr("https://example.com/landing?ref=abc")

    result = build_redirect_url(qr)

    assert result == "https://example.com/landing?ref=abc"


def test_build_redirect_url_records_latency_metric() -> None:
    reset_metrics_collector()
    qr = _build_qr("https://example.com/landing")

    _ = build_redirect_url(qr)

    snapshot = get_metrics_collector().snapshot()
    assert snapshot.redirect_latency_count == 1
    assert snapshot.redirect_latency_avg_ms >= 0


def test_build_redirect_url_records_queue_lag_metric_when_enqueued_time_given() -> None:
    reset_metrics_collector()
    qr = _build_qr("https://example.com/landing")
    enqueued_at = datetime.now(UTC) - timedelta(seconds=5)

    _ = build_redirect_url(qr, scan_enqueued_at=enqueued_at)

    snapshot = get_metrics_collector().snapshot()
    assert snapshot.queue_lag_count == 1
    assert snapshot.queue_lag_avg_seconds >= 4


