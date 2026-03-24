"""Google Analytics helpers for redirect enrichment and measurement payloads."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class GoogleAnalyticsService:
    """Build GA-aware redirect URLs and GA4 measurement payload structures."""

    def enrich_redirect_url(
        self,
        *,
        destination_url: str,
        ga_measurement_id: str | None,
        utm_source: str | None,
        utm_medium: str | None,
        utm_campaign: str | None,
    ) -> str:
        """Append GA/UTM query parameters to destination URLs when configured."""

        split_result = urlsplit(destination_url)
        params: dict[str, str] = dict(parse_qsl(split_result.query, keep_blank_values=False))

        if ga_measurement_id:
            params["ga_measurement_id"] = ga_measurement_id
        if utm_source:
            params["utm_source"] = utm_source
        if utm_medium:
            params["utm_medium"] = utm_medium
        if utm_campaign:
            params["utm_campaign"] = utm_campaign

        return urlunsplit(
            (
                split_result.scheme,
                split_result.netloc,
                split_result.path,
                urlencode(params),
                split_result.fragment,
            )
        )

    def build_measurement_payload(
        self,
        *,
        measurement_id: str,
        api_secret: str,
        client_id: str,
        qr_id: int,
        short_code: str,
        destination_url: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build GA4 Measurement Protocol payload for post-scan attribution."""

        event_params: dict[str, Any] = {
            "qr_id": qr_id,
            "short_code": short_code,
            "destination_url": destination_url,
        }
        if metadata:
            event_params.update(metadata)

        return {
            "measurement_id": measurement_id,
            "api_secret": api_secret,
            "client_id": client_id,
            "events": [
                {
                    "name": "qr_scan_redirect",
                    "params": event_params,
                }
            ],
        }

