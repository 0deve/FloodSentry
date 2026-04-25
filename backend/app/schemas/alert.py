"""Pydantic schemas for Alert."""

from datetime import datetime
from pydantic import BaseModel, Field


class AlertBase(BaseModel):
    """Base schema for alerts."""

    nuts_id: str = Field(..., max_length=10, examples=["RO224"])
    level: str = Field(
        ...,
        max_length=20,
        examples=["critical"],
        description="One of: info, warning, critical, emergency",
    )
    title: str = Field(..., max_length=300)
    description: str | None = Field(default=None, max_length=2000)


class AlertCreate(AlertBase):
    """Schema for creating a new alert."""

    prediction_id: int | None = None


class AlertResponse(AlertBase):
    """Schema for alert API responses."""

    id: int
    prediction_id: int | None = None
    is_active: bool
    created_at: datetime
    resolved_at: datetime | None = None

    model_config = {"from_attributes": True}
