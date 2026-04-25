"""Pydantic schemas for FloodPrediction."""

from datetime import datetime
from pydantic import BaseModel, Field


class PredictionBase(BaseModel):
    """Base schema for flood predictions."""

    nuts_id: str = Field(..., max_length=10, examples=["RO224"])
    risk_score: float = Field(..., ge=0, le=100, examples=[91.2])
    hazard_type: str = Field(
        default="fluvial",
        max_length=50,
        examples=["fluvial"],
        description="One of: fluvial, pluvial, snowmelt",
    )
    affected_population: int | None = Field(default=None, ge=0, examples=[12000])

    # ML Features
    rainfall_mm: float | None = None
    soil_moisture: float | None = None
    ndwi: float | None = None
    snow_water_equivalent: float | None = None
    river_discharge: float | None = None
    temperature_c: float | None = None


class PredictionCreate(PredictionBase):
    """Schema for creating a new prediction."""

    pass


class PredictionResponse(PredictionBase):
    """Schema for prediction API responses."""

    id: int
    predicted_at: datetime
    model_version: str | None = None

    model_config = {"from_attributes": True}
