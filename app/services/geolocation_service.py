"""IP geolocation service for resolving country and city from IP addresses."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from geoip2.database import Reader
    from geoip2.models import City

logger = logging.getLogger(__name__)

# Default path for GeoLite2 City database
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "GeoLite2-City.mmdb"


class GeolocationService:
    """Service for IP address geolocation lookups."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Initialize with path to MaxMind GeoLite2 City database.

        Args:
            db_path: Path to GeoLite2-City.mmdb file. If None, uses default path.
        """
        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._reader: Reader | None = None
        self._load_database()

    def _load_database(self) -> None:
        """Load the GeoIP2 database if available."""
        try:
            from geoip2.database import Reader

            if self._db_path.exists():
                self._reader = Reader(str(self._db_path))
                logger.info("Loaded GeoIP2 database from %s", self._db_path)
            else:
                logger.warning(
                    "GeoIP2 database not found at %s. "
                    "Download from https://dev.maxmind.com/geoip/geolite2-free-geolocation-data",
                    self._db_path,
                )
        except ImportError:
            logger.error("geoip2 library not installed. Run: pip install geoip2")
        except Exception as exc:
            logger.exception("Failed to load GeoIP2 database: %s", exc)

    def lookup(self, ip_address: str | None) -> tuple[str | None, str | None]:
        """Lookup country and city from IP address.

        Tries local database first, falls back to HTTP API if unavailable.

        Args:
            ip_address: IPv4 or IPv6 address string.

        Returns:
            Tuple of (country_name, city_name). Both None if lookup fails.
        """
        if not ip_address:
            return None, None

        # Skip private/reserved IP addresses
        if self._is_private_ip(ip_address):
            return None, None

        # Try local database first
        if self._reader:
            try:
                response: City = self._reader.city(ip_address)
                country = response.country.name
                city = response.city.name
                return country, city
            except Exception as exc:
                logger.debug("GeoIP lookup failed for %s: %s", ip_address, exc)

        # Fallback to HTTP API
        return self._lookup_via_api(ip_address)

    def _lookup_via_api(self, ip_address: str) -> tuple[str | None, str | None]:
        """Fallback HTTP API lookup using ip-api.com (free, no auth needed)."""
        try:
            # ip-api.com allows 45 requests/minute for free without API key
            response = httpx.get(
                f"http://ip-api.com/json/{ip_address}?fields=status,country,city",
                timeout=5,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "success":
                return data.get("country"), data.get("city")
        except Exception as exc:
            logger.debug("HTTP geolocation API failed for %s: %s", ip_address, exc)

        return None, None

    def _is_private_ip(self, ip: str) -> bool:
        """Check if IP is private/local/reserved."""
        try:
            import ipaddress

            addr = ipaddress.ip_address(ip)
            return addr.is_private or addr.is_loopback or addr.is_reserved
        except ValueError:
            return True

    def close(self) -> None:
        """Close the database reader."""
        if self._reader:
            self._reader.close()
            self._reader = None


# Global singleton instance
_geolocation_service: GeolocationService | None = None


def get_geolocation_service() -> GeolocationService:
    """Get or create the global geolocation service instance."""
    global _geolocation_service
    if _geolocation_service is None:
        # Allow override via environment variable
        db_path = os.getenv("GEOLITE2_DB_PATH")
        _geolocation_service = GeolocationService(db_path)
    return _geolocation_service


def parse_ip_location(ip_address: str | None) -> tuple[str | None, str | None]:
    """Convenience function to lookup IP location without managing service.

    Args:
        ip_address: IP address to lookup.

    Returns:
        Tuple of (country, city) or (None, None) if unavailable.
    """
    service = get_geolocation_service()
    return service.lookup(ip_address)
