#!/usr/bin/env python3
"""Log API responses (and errors) to timestamped files.

Usage examples:
  python scripts/log_api_response.py --access-token <TOKEN>
  python scripts/log_api_response.py --email longthan243@gmail.com  --password longthan243

Set-Location "D:\Documents\Do an tot nghiep\DynamicQR_backend"
.\.venv\Scripts\python.exe scripts\log_api_response.py --email longthan243@gmail.com  --password longthan243

"""

from __future__ import annotations

import argparse
import json
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


def build_url(base_url: str, endpoint: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", endpoint.lstrip("/"))


def http_json_request(
    *,
    url: str,
    method: str,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = 20,
    verify_ssl: bool = True,
) -> tuple[int, str, Any]:
    body_bytes = None
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)

    if payload is not None:
        request_headers["Content-Type"] = "application/json"
        body_bytes = json.dumps(payload).encode("utf-8")

    request = Request(url=url, data=body_bytes, headers=request_headers, method=method.upper())

    ssl_context = None
    if not verify_ssl:
        ssl_context = ssl._create_unverified_context()

    with urlopen(request, timeout=timeout, context=ssl_context) as response:
        raw = response.read().decode("utf-8", errors="replace")
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type.lower():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"raw": raw}
        else:
            parsed = {"raw": raw}
        return response.status, raw, parsed


def resolve_access_token(args: argparse.Namespace) -> str:
    if args.access_token:
        return args.access_token

    if not args.email or not args.password:
        raise ValueError("Provide --access-token, or both --email and --password.")

    login_url = build_url(args.base_url, args.login_path)
    status, _, parsed = http_json_request(
        url=login_url,
        method="POST",
        payload={"email": args.email, "password": args.password},
        timeout=args.timeout,
        verify_ssl=args.verify_ssl,
    )
    if status < 200 or status >= 300:
        raise RuntimeError(f"Login failed with status {status}.")

    if not isinstance(parsed, dict) or not parsed.get("access_token"):
        raise RuntimeError("Login succeeded but access_token is missing.")

    return str(parsed["access_token"])


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def print_ga4_codes_to_terminal(parsed: Any) -> None:
    """Print GA4 property and measurement-id rows to terminal."""

    if not isinstance(parsed, dict):
        print("[GA4] Response is not a JSON object; cannot extract GA4 properties.")
        return

    items = parsed.get("items")
    if not isinstance(items, list):
        print("[GA4] No 'items' array in response.")
        return

    if not items:
        print("[GA4] No GA4 properties returned (items is empty).")
        return

    print("[GA4] Properties and measurement IDs:")
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        property_id = str(item.get("property_id", "")) or "<unknown-property-id>"
        display_name = str(item.get("display_name", "")) or "<no-display-name>"
        measurement_id = str(item.get("ga_measurement_id", "")).strip() or "<none>"
        print(f"  {idx}. property_id={property_id} | display_name={display_name} | ga_measurement_id={measurement_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Log API response to files.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--endpoint", default="/api/v1/ga4/properties")
    parser.add_argument("--access-token", default="")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--login-path", default="/api/v1/auth/login")
    parser.add_argument("--out-dir", default="logs")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--verify-ssl", action="store_true", default=False)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    json_log = out_dir / f"api-response-{timestamp}.json"
    meta_log = out_dir / f"api-response-{timestamp}.txt"

    url = build_url(args.base_url, args.endpoint)

    try:
        token = resolve_access_token(args)
        headers = {"Authorization": f"Bearer {token}"}
        status, raw, parsed = http_json_request(
            url=url,
            method="GET",
            headers=headers,
            timeout=args.timeout,
            verify_ssl=args.verify_ssl,
        )

        if isinstance(parsed, (dict, list)):
            write_text(json_log, json.dumps(parsed, ensure_ascii=True, indent=2))
        else:
            write_text(json_log, json.dumps({"raw": raw}, ensure_ascii=True, indent=2))

        meta = "\n".join(
            [
                f"timestamp={datetime.now(timezone.utc).isoformat()}",
                f"url={url}",
                f"status={status}",
                f"json_log={json_log}",
            ]
        )
        write_text(meta_log, meta + "\n")

        print("[OK] API response logged")
        print(f"  URL: {url}")
        print(f"  JSON: {json_log}")
        print(f"  META: {meta_log}")
        print_ga4_codes_to_terminal(parsed)
        return 0

    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        meta = "\n".join(
            [
                f"timestamp={datetime.now(timezone.utc).isoformat()}",
                f"url={url}",
                f"status=failed",
                f"http_status={exc.code}",
                f"error={exc.reason}",
                f"response_body={body}",
            ]
        )
        write_text(meta_log, meta + "\n")
        print("[ERROR] HTTP error")
        print(f"  URL: {url}")
        print(f"  META: {meta_log}")
        return 1

    except URLError as exc:
        meta = "\n".join(
            [
                f"timestamp={datetime.now(timezone.utc).isoformat()}",
                f"url={url}",
                "status=failed",
                f"error={exc.reason}",
            ]
        )
        write_text(meta_log, meta + "\n")
        print("[ERROR] Network error")
        print(f"  URL: {url}")
        print(f"  META: {meta_log}")
        return 1

    except Exception as exc:  # noqa: BLE001
        meta = "\n".join(
            [
                f"timestamp={datetime.now(timezone.utc).isoformat()}",
                f"url={url}",
                "status=failed",
                f"error={str(exc)}",
            ]
        )
        write_text(meta_log, meta + "\n")
        print("[ERROR] Request failed")
        print(f"  URL: {url}")
        print(f"  META: {meta_log}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

