"""Tests for scan metadata extraction service."""

from __future__ import annotations

from starlette.requests import Request

from app.services.scan_metadata_service import extract_scan_metadata


def _build_request(headers: list[tuple[bytes, bytes]], client: tuple[str, int]) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/q/abc123",
        "raw_path": b"/q/abc123",
        "query_string": b"",
        "headers": headers,
        "client": client,
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


def test_extract_scan_metadata_prefers_forwarded_ip_and_parses_ua() -> None:
    request = _build_request(
        headers=[
            (b"x-forwarded-for", b"203.0.113.1, 10.0.0.1"),
            (
                b"user-agent",
                b"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                b"(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            ),
            (b"referer", b"https://example.com/campaign"),
        ],
        client=("127.0.0.1", 12345),
    )

    metadata = extract_scan_metadata(request)

    assert metadata.ip_address == "203.0.113.1"
    assert metadata.device_type == "desktop"
    assert metadata.os == "Windows"
    assert metadata.browser == "Chrome"
    assert metadata.referer == "https://example.com/campaign"


def test_extract_scan_metadata_falls_back_to_client_ip_and_unknowns() -> None:
    request = _build_request(
        headers=[
            (b"user-agent", b"CustomAgent/1.0"),
        ],
        client=("198.51.100.10", 5555),
    )

    metadata = extract_scan_metadata(request)

    assert metadata.ip_address == "198.51.100.10"
    assert metadata.os == "Unknown"
    assert metadata.browser == "Unknown"

