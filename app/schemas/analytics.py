"""Schemas for analytics summary query inputs and API responses."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class AnalyticsSummaryRow(BaseModel):
    """One aggregated day-level analytics row from summary storage."""

    model_config = ConfigDict(from_attributes=True)

    summary_date: date
    total_scans: int = Field(ge=0)
    unique_visitors: int = Field(ge=0)


class AnalyticsSummaryRequest(BaseModel):
    """Range query payload for daily summary analytics retrieval."""

    qr_id: int = Field(gt=0)
    start_date: date
    end_date: date


class AnalyticsSummaryResponse(BaseModel):
    """Dashboard-ready analytics response built from summary rows."""

    qr_id: int
    start_date: date
    end_date: date
    total_scans: int = Field(ge=0)
    unique_visitors: int = Field(ge=0)
    rows: list[AnalyticsSummaryRow]

