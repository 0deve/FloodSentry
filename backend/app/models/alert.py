"""Alert model — Generated alerts based on prediction thresholds."""

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from datetime import datetime, timezone

from app.database import Base


class Alert(Base):
    """Represents a flood alert triggered when risk exceeds thresholds.

    Alert levels:
    - info: risk_score < 30
    - warning: 30 <= risk_score < 60
    - critical: 60 <= risk_score < 85
    - emergency: risk_score >= 85
    """

    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    nuts_id = Column(
        String(10),
        ForeignKey("locations.nuts_id"),
        nullable=False,
        index=True,
    )
    prediction_id = Column(
        Integer,
        ForeignKey("flood_predictions.id"),
        nullable=True,
    )
    level = Column(String(20), nullable=False)  # info, warning, critical, emergency
    title = Column(String(300), nullable=False)
    description = Column(String(2000), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    resolved_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Alert(level='{self.level}', nuts_id='{self.nuts_id}')>"
