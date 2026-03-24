"""Tests for Google Analytics URL and payload helpers."""

from __future__ import annotations

from app.services.google_analytics_service import GoogleAnalyticsService


def test_enrich_redirect_url_appends_utm_and_measurement_id() -> None:
    service = GoogleAnalyticsService()

    url = service.enrich_redirect_url(
        destination_url="https://example.com/landing",
        ga_measurement_id="G-ABC123",
        utm_source="newsletter",
        utm_medium="email",
        utm_campaign="launch-2026",
    )

    assert "ga_measurement_id=G-ABC123" in url
    assert "utm_source=newsletter" in url
    assert "utm_medium=email" in url
    assert "utm_campaign=launch-2026" in url


def test_build_measurement_payload_returns_expected_event_shape() -> None:
    service = GoogleAnalyticsService()

    payload = service.build_measurement_payload(
        measurement_id="G-ABC123",
        api_secret="secret",
        client_id="client-1",
        qr_id=10,
        short_code="abC12z",
        destination_url="https://example.com/offer",
        metadata={"device_type": "mobile"},
    )

    assert payload["measurement_id"] == "G-ABC123"
    assert payload["events"][0]["name"] == "qr_scan_redirect"
    assert payload["events"][0]["params"]["qr_id"] == 10
    assert payload["events"][0]["params"]["device_type"] == "mobile"

