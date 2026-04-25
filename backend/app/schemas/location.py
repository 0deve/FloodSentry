"""Pydantic schemas for Location (NUTS regions)."""

from pydantic import BaseModel, Field


class LocationBase(BaseModel):
    """Base schema for Location data."""

    nuts_id: str = Field(..., max_length=10, examples=["RO224"])
    name: str = Field(..., max_length=200, examples=["Județul Galați"])
    level: int = Field(default=3, ge=0, le=3, description="NUTS level (0-3)")
    population: int | None = Field(default=None, ge=0, examples=[490000])
    latitude: float = Field(..., ge=-90, le=90, examples=[45.44])
    longitude: float = Field(..., ge=-180, le=180, examples=[28.05])


class LocationCreate(LocationBase):
    """Schema for creating a new location."""

    pass


class LocationUpdate(BaseModel):
    """Schema for updating an existing location (all fields optional)."""

    name: str | None = Field(default=None, max_length=200)
    level: int | None = Field(default=None, ge=0, le=3)
    population: int | None = Field(default=None, ge=0)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class LocationResponse(LocationBase):
    """Schema for location API responses."""

    id: int

    model_config = {"from_attributes": True}


class LocationWithInfrastructure(LocationResponse):
    """Location response including related critical infrastructure."""

    infrastructure: list["InfrastructureResponse"] = []

    model_config = {"from_attributes": True}


# Forward reference resolution
from app.schemas.infrastructure import InfrastructureResponse  # noqa: E402

LocationWithInfrastructure.model_rebuild()
