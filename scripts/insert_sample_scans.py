"""Insert sample scans for campaigns 24 and 25."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.db.session import get_db_session


async def insert_sample_scans() -> None:
    """Insert 20 sample scans across QR codes from campaigns 24 and 25."""

    async for session in get_db_session():
        # QR codes: 23 (campaign 24), 30 (campaign 25)
        qr_ids = [23, 30]
        
        # Get qr_config_id for each QR code from qr_configurations
        qr_config_ids = {}
        for qr_id in qr_ids:
            result = await session.execute(text("""
                SELECT id FROM qr_configurations 
                WHERE qr_id = :qr_id AND is_current = 1 
                LIMIT 1
            """), {"qr_id": qr_id})
            row = result.scalar()
            if row:
                qr_config_ids[qr_id] = row
                print(f"QR {qr_id} -> qr_configurations_id {row}")
        
        if not qr_config_ids:
            print("ERROR: No current qr_configurations found for these QR codes")
            return
        
        # Sample device info variations
        devices = [
            ("192.168.1.100", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Desktop", "Windows", "Chrome"),
            ("192.168.1.101", "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15", "Mobile", "iOS", "Safari"),
            ("192.168.1.102", "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36", "Mobile", "Android", "Chrome"),
            ("203.0.113.50", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36", "Desktop", "macOS", "Safari"),
            ("203.0.113.51", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36", "Desktop", "Linux", "Firefox"),
        ]
        
        # Insert 10 scans per QR code (20 total)
        insert_count = 0
        now = datetime.now(UTC)
        
        for qr_id in qr_ids:
            qr_config_id = qr_config_ids[qr_id]
            
            for i in range(10):
                ip_addr, user_agent, device_type, os_type, browser = devices[i % len(devices)]
                scanned_at = now - timedelta(hours=20-i, minutes=i*5)
                
                await session.execute(text("""
                    INSERT INTO scan_logs (
                        qr_configurations_id, scanned_at,
                        ip_address, user_agent, device_type, os, browser
                    ) VALUES (
                        :qr_config_id, :scanned_at,
                        :ip_addr, :user_agent, :device_type, :os_type, :browser
                    )
                """), {
                    "qr_config_id": qr_config_id,
                    "scanned_at": scanned_at,
                    "ip_addr": ip_addr,
                    "user_agent": user_agent,
                    "device_type": device_type,
                    "os_type": os_type,
                    "browser": browser,
                })
                insert_count += 1

        await session.commit()
        print(f"\n✅ Inserted {insert_count} sample scans")
        
        # Verify inserts - count scans by qr configurations
        result = await session.execute(text("""
            SELECT COUNT(DISTINCT sl.id) as total_scans
            FROM scan_logs sl
            WHERE sl.qr_configurations_id IN (19, 43)
        """))
        total_scans = result.scalar()
        print(f"Total scans in scan_logs for qr_configurations 19, 43: {total_scans}")


if __name__ == "__main__":
    asyncio.run(insert_sample_scans())

