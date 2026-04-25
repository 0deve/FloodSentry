"""Pydantic schemas for CriticalInfrastructure."""

from pydantic import BaseModel, Field


class InfrastructureBase(BaseModel):
    """Base schema for critical infrastructure."""

    nuts_id: str = Field(..., max_length=10, examples=["RO224"])
    type: str = Field(
        ...,
        max_length=50,
        examples=["hospital"],
        description="Type: hospital, school, power_station, road",
    )
    name: str = Field(
        ..., max_length=200, examples=["Spitalul Județean Sf. Apostol Andrei"]
    )
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class InfrastructureCreate(InfrastructureBase):
    """Schema for creating infrastructure."""

    pass


class InfrastructureResponse(InfrastructureBase):
    """Schema for infrastructure API responses."""

    id: int

    model_config = {"from_attributes": True}
