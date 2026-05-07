"""QR Code SQLAlchemy model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.campaigns import Campaign
    from app.models.scan_logs import ScanLog


class QRCode(Base, TimestampMixin, SoftDeleteMixin):
    """QR Code model representing individual QR codes."""

    __tablename__ = "qr_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    destination_url: Mapped[str] = mapped_column(Text, nullable=False)
    qr_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)

    # Relationships
    campaign: Mapped[Campaign | None] = relationship("Campaign", back_populates="qr_codes")
    scan_logs: Mapped[list[ScanLog]] = relationship(
        "ScanLog", back_populates="qr_code", cascade="all, delete-orphan"
    )
