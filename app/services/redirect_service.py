"""Redirect URL composition helpers."""

from __future__ import annotations

from datetime import datetime
from time import monotonic
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.metrics import compute_queue_lag_seconds, get_metrics_collector
from app.schemas.redirect import RedirectQRCode


def build_redirect_url(
    qr_code: RedirectQRCode,
    *,
    request_started_at: float | None = None,
    scan_enqueued_at: datetime | None = None,
) -> str:
    """Build the final redirect URL with configured UTM parameters."""

    started_at = request_started_at if request_started_at is not None else monotonic()

    url_parts = urlsplit(qr_code.destination_url)
    query_items = dict(parse_qsl(url_parts.query, keep_blank_values=True))

    if qr_code.utm_source:
        query_items["utm_source"] = qr_code.utm_source
    if qr_code.utm_medium:
        query_items["utm_medium"] = qr_code.utm_medium
    if qr_code.utm_campaign:
        query_items["utm_campaign"] = qr_code.utm_campaign

    updated_query = urlencode(query_items)
    redirect_url = urlunsplit(
        (
            url_parts.scheme,
            url_parts.netloc,
            url_parts.path,
            updated_query,
            url_parts.fragment,
        )
    )

    metrics = get_metrics_collector()
    metrics.observe_redirect_latency_ms((monotonic() - started_at) * 1000.0)

    if scan_enqueued_at is not None:
        metrics.observe_queue_lag_seconds(compute_queue_lag_seconds(scan_enqueued_at))

    return redirect_url

