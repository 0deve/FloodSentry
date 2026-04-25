"""Pydantic schemas for FloodSentry API."""

from app.schemas.location import (
    LocationCreate,
    LocationUpdate,
    LocationResponse,
    LocationWithInfrastructure,
)
from app.schemas.infrastructure import (
    InfrastructureCreate,
    InfrastructureResponse,
)
from app.schemas.prediction import (
    PredictionCreate,
    PredictionResponse,
)
from app.schemas.alert import (
    AlertCreate,
    AlertResponse,
)
from app.schemas.impact import (
    ImpactSummaryResponse,
    RegionImpact,
    InfrastructureAtRisk,
)

__all__ = [
    "LocationCreate",
    "LocationUpdate",
    "LocationResponse",
    "LocationWithInfrastructure",
    "InfrastructureCreate",
    "InfrastructureResponse",
    "PredictionCreate",
    "PredictionResponse",
    "AlertCreate",
    "AlertResponse",
    "ImpactSummaryResponse",
    "RegionImpact",
    "InfrastructureAtRisk",
]
