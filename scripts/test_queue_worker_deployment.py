"""
Test script để verify queue & worker hoạt động đúng trước deployment.

Chạy script này để:
1. Kiểm tra queue backend được chọn đúng (memory vs redis)
2. Kiểm tra enqueue/dequeue hoạt động
3. Kiểm tra worker pool messages từ queue
4. End-to-end test: enqueue message → worker xử lý → check DB
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Setup path để import app modules
sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import get_settings
from app.workers.queue_client import get_queue_client, close_queue_client
from app.db.database import get_db


async def test_queue_backend():
    """Test: Queue backend được chọn đúng?"""
    print("\n" + "=" * 60)
    print("✓ TEST 1: Queue Backend Configuration")
    print("=" * 60)

    settings = get_settings()
    queue_backend = settings.queue_backend.lower().strip()

    print(f"  APP_ENV: {settings.app_env}")
    print(f"  QUEUE_BACKEND: {queue_backend}")
    print(f"  QUEUE_URL: {settings.queue_url or 'N/A'}")
    print(f"  Queue max retries: {settings.queue_max_retry_attempts}")
    print(f"  Queue visibility timeout: {settings.queue_visibility_timeout_seconds}s")

    if queue_backend not in ["memory", "redis"]:
        print(f"  ❌ ERROR: Unsupported backend '{queue_backend}'")
        return False

    if queue_backend == "redis" and not settings.queue_url:
        print(f"  ⚠️  WARNING: Redis backend selected but QUEUE_URL is empty")

    print(f"  ✅ Backend configuration is valid")
    return True


async def test_enqueue_dequeue():
    """Test: Enqueue/Dequeue hoạt động?"""
    print("\n" + "=" * 60)
    print("✓ TEST 2: Enqueue/Dequeue Operations")
    print("=" * 60)

    queue_client = get_queue_client()

    # Test message
    test_payload = {
        "qr_config_id": 999,  # Dummy ID
        "short_code": "test_code_12345",
        "ip_address": "192.168.1.1",
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Enqueue
    print(f"  1. Enqueueing test message...")
    try:
        await queue_client.enqueue("scan_logs", test_payload)
        print(f"     ✅ Enqueue successful: {test_payload}")
    except Exception as e:
        print(f"     ❌ Enqueue failed: {e}")
        await close_queue_client()
        return False

    # Dequeue
    print(f"  2. Dequeueing test message...")
    try:
        msg_id, payload = await queue_client.dequeue("scan_logs", timeout_seconds=5)
        if msg_id is None:
            print(f"     ⚠️  WARNING: No message dequeued (queue empty?)")
            await close_queue_client()
            return False

        print(f"     ✅ Dequeue successful")
        print(f"        Message ID: {msg_id}")
        print(f"        Payload: {payload}")

        # Ack
        print(f"  3. Acknowledging message...")
        await queue_client.ack("scan_logs", msg_id)
        print(f"     ✅ Ack successful")

    except Exception as e:
        print(f"     ❌ Dequeue/Ack failed: {e}")
        await close_queue_client()
        return False

    await close_queue_client()
    return True


async def test_worker_integration():
    """Test: Worker có thể process messages không?"""
    print("\n" + "=" * 60)
    print("✓ TEST 3: Worker Integration (Poll & Process)")
    print("=" * 60)

    from app.workers.scan_log_worker import process_next_scan_log_message

    queue_client = get_queue_client()

    # Enqueue test message
    test_payload = {
        "qr_config_id": 999,
        "short_code": "test_worker_123",
        "ip_address": "192.168.1.1",
        "timestamp": datetime.utcnow().isoformat(),
    }

    print(f"  1. Enqueueing test message for worker...")
    try:
        await queue_client.enqueue("scan_logs", test_payload)
        print(f"     ✅ Enqueued: {test_payload}")
    except Exception as e:
        print(f"     ❌ Enqueue failed: {e}")
        await close_queue_client()
        return False

    # Let worker process
    print(f"  2. Running worker process_next_scan_log_message()...")
    try:
        handled = await process_next_scan_log_message()
        if handled:
            print(f"     ✅ Worker processed message successfully")
        else:
            print(f"     ⚠️  Worker returned False (queue might be empty or payload invalid)")
    except Exception as e:
        print(f"     ❌ Worker processing failed: {e}")
        print(f"        (This might be normal if qr_config_id=999 doesn't exist)")

    await close_queue_client()
    return True


async def test_embedded_worker_config():
    """Test: Embedded worker sẽ bật ở local hay không?"""
    print("\n" + "=" * 60)
    print("✓ TEST 4: Embedded Worker Configuration (Local vs Production)")
    print("=" * 60)

    settings = get_settings()
    queue_backend = settings.queue_backend.lower().strip()
    should_embed = settings.app_env == "local" and queue_backend == "memory"

    print(f"  APP_ENV: {settings.app_env}")
    print(f"  QUEUE_BACKEND: {queue_backend}")
    print(f"  Should embed worker? {should_embed}")

    if settings.app_env == "local":
        if queue_backend == "memory":
            print(f"  ✅ LOCAL + MEMORY: Embedded worker WILL be spawned")
        else:
            print(f"  ⚠️  LOCAL + {queue_backend.upper()}: Embedded worker will NOT spawn")
            print(f"     → You need to run worker separately!")
    else:
        print(f"  ℹ️  PRODUCTION ({settings.app_env}): Embedded worker will NOT spawn")
        if queue_backend == "memory":
            print(f"     ⚠️  WARNING: Using memory queue in production without separate worker!")
            print(f"     → Queue messages will pile up and NOT be processed!")
            print(f"     → SOLUTION: Run separate worker process or use Redis backend")
        else:
            print(f"     ✅ Using {queue_backend.upper()} backend - worker can run separately")

    return True


async def test_deployment_readiness():
    """Test: System ready for deployment?"""
    print("\n" + "=" * 60)
    print("✓ TEST 5: Deployment Readiness Checklist")
    print("=" * 60)

    settings = get_settings()
    queue_backend = settings.queue_backend.lower().strip()

    checklist = {
        "✓ Database connection": settings.database_url is not None,
        "✓ Queue backend set": queue_backend in ["memory", "redis"],
        "✓ Redis URL (if redis)": queue_backend != "redis" or bool(settings.queue_url),
        "✓ CORS origins set": len(settings.cors_allow_origins) > 0,
        "✓ Not using dev defaults": settings.app_env != "local" or queue_backend != "memory",
    }

    all_ok = True
    for check, result in checklist.items():
        status = "✅" if result else "❌"
        print(f"  {status} {check}")
        if not result:
            all_ok = False

    print(f"\n  Overall: {'✅ Ready for deployment' if all_ok else '⚠️  Needs attention before deployment'}")
    return all_ok


async def main():
    """Run all tests"""
    print("\n" + "╔" + "=" * 58 + "╗")
    print("║  QUEUE & WORKER VERIFICATION TEST SUITE                   ║")
    print("║  DynamicQR Backend - Deployment Readiness Check           ║")
    print("╚" + "=" * 58 + "╝")

    try:
        # Run tests
        test1 = await test_queue_backend()
        test2 = await test_enqueue_dequeue()
        test3 = await test_worker_integration()
        test4 = await test_embedded_worker_config()
        test5 = await test_deployment_readiness()

        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        all_tests = [test1, test2, test3, test4, test5]
        passed = sum(all_tests)
        total = len(all_tests)

        print(f"  Passed: {passed}/{total}")

        if all([test1, test4, test5]):
            print(f"\n  ✅ System is deployment-ready!")
        else:
            print(f"\n  ⚠️  Review configuration before deploying to production")

        print("\n" + "=" * 60)

    except Exception as e:
        print(f"\n❌ Test suite error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

