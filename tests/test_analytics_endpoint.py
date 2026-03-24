"""Tests for analytics dashboard endpoint responses."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.v1.analytics import get_analytics_service
from app.schemas.analytics import AnalyticsSummaryResponse, AnalyticsSummaryRow


class _StubAnalyticsService:
    async def get_qr_summary(self, *, qr_id: int, start_date: date, end_date: date) -> AnalyticsSummaryResponse:
        return AnalyticsSummaryResponse(
            qr_id=qr_id,
            start_date=start_date,
            end_date=end_date,
            total_scans=25,
            unique_visitors=20,
            rows=[
                AnalyticsSummaryRow(summary_date=start_date, total_scans=10, unique_visitors=8),
                AnalyticsSummaryRow(summary_date=end_date, total_scans=15, unique_visitors=12),
            ],
        )


@pytest.mark.asyncio
async def test_get_qr_analytics_returns_summary_payload(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_analytics_service] = lambda: _StubAnalyticsService()

    try:
        response = await async_client.get(
            "/api/v1/analytics/11?start_date=2026-03-20&end_date=2026-03-24"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["qr_id"] == 11
    assert body["total_scans"] == 25
    assert len(body["rows"]) == 2

