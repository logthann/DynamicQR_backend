"""Scan metadata extraction utilities for redirect tracking."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import Request

from app.schemas.redirect import RedirectScanMetadata


def _extract_client_ip(headers: Mapping[str, str], fallback_ip: str | None) -> str | None:
    """Resolve client IP with proxy-aware fallback order."""

    x_forwarded_for = headers.get("x-forwarded-for")
    if x_forwarded_for:
        first = x_forwarded_for.split(",", maxsplit=1)[0].strip()
        if first:
            return first

    x_real_ip = headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip.strip() or fallback_ip

    return fallback_ip


def _parse_user_agent(user_agent: str | None) -> tuple[str, str, str]:
    """Best-effort user-agent parsing for device, OS, and browser."""

    ua = (user_agent or "").lower()

    if "mobile" in ua or "iphone" in ua or "android" in ua:
        device_type = "mobile"
    elif "ipad" in ua or "tablet" in ua:
        device_type = "tablet"
    else:
        device_type = "desktop"

    if "windows" in ua:
        os_name = "Windows"
    elif "android" in ua:
        os_name = "Android"
    elif "iphone" in ua or "ipad" in ua or "ios" in ua:
        os_name = "iOS"
    elif "mac os" in ua or "macintosh" in ua:
        os_name = "macOS"
    elif "linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Unknown"

    if "edg/" in ua:
        browser = "Edge"
    elif "chrome/" in ua and "edg/" not in ua:
        browser = "Chrome"
    elif "firefox/" in ua:
        browser = "Firefox"
    elif "safari/" in ua and "chrome/" not in ua:
        browser = "Safari"
    else:
        browser = "Unknown"

    return device_type, os_name, browser


def extract_scan_metadata(request: Request) -> RedirectScanMetadata:
    """Build normalized scan metadata from an inbound HTTP request."""

    headers = request.headers
    fallback_ip = request.client.host if request.client else None
    client_ip = _extract_client_ip(headers, fallback_ip)

    user_agent = headers.get("user-agent")
    device_type, os_name, browser = _parse_user_agent(user_agent)

    return RedirectScanMetadata(
        ip_address=client_ip,
        user_agent=user_agent,
        device_type=device_type,
        os=os_name,
        browser=browser,
        country=None,
        city=None,
        referer=headers.get("referer"),
    )

