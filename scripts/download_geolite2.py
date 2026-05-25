"""Download MaxMind GeoLite2 City database for IP geolocation.

Usage:
    python scripts/download_geolite2.py <your_maxmind_license_key>

Get a free license key at: https://dev.maxmind.com/geoip/geolite2-free-geolocation-data
"""

from __future__ import annotations

import gzip
import os
import shutil
import sys
from pathlib import Path

import httpx

GEOLITE2_URL = "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key={license_key}&suffix=tar.gz"
DATA_DIR = Path(__file__).parent.parent / "data"


def download_geolite2(license_key: str) -> Path | None:
    """Download and extract GeoLite2-City database.

    Args:
        license_key: MaxMind license key.

    Returns:
        Path to extracted .mmdb file or None if failed.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    url = GEOLITE2_URL.format(license_key=license_key)
    tar_path = DATA_DIR / "GeoLite2-City.tar.gz"

    print(f"Downloading GeoLite2-City database...")

    try:
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            response = client.get(url)
            response.raise_for_status()
            tar_path.write_bytes(response.content)
        print(f"Downloaded to {tar_path}")

        # Extract tar.gz
        import tarfile

        print("Extracting database...")
        with tarfile.open(tar_path, "r:gz") as tar:
            # Find the .mmdb file inside the tar
            mmdb_member = None
            for member in tar.getmembers():
                if member.name.endswith(".mmdb"):
                    mmdb_member = member
                    break

            if mmdb_member is None:
                print("ERROR: No .mmdb file found in archive")
                return None

            # Extract just the mmdb file
            tar.extract(mmdb_member, DATA_DIR)

        # Move to standard location
        extracted_mmdb = DATA_DIR / mmdb_member.name
        target_mmdb = DATA_DIR / "GeoLite2-City.mmdb"

        if extracted_mmdb.exists():
            shutil.move(str(extracted_mmdb), str(target_mmdb))
            # Clean up subdirectories
            for subdir in DATA_DIR.iterdir():
                if subdir.is_dir() and subdir.name.startswith("GeoLite2"):
                    shutil.rmtree(subdir)

        # Remove tar.gz
        tar_path.unlink()

        print(f"✓ GeoIP database ready at: {target_mmdb}")
        return target_mmdb

    except Exception as exc:
        print(f"ERROR: Failed to download/extract database: {exc}")
        return None


def main() -> int:
    """Main entry point."""
    license_key = os.getenv("MAXMIND_LICENSE_KEY")

    if len(sys.argv) > 1:
        license_key = sys.argv[1]

    if not license_key:
        print("Usage: python scripts/download_geolite2.py <license_key>")
        print("Or set MAXMIND_LICENSE_KEY environment variable")
        print("\nGet a free license key at: https://dev.maxmind.com/geoip/geolite2-free-geolocation-data")
        return 1

    result = download_geolite2(license_key)
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
