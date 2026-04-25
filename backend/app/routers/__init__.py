"""API routers for FloodSentry."""

from app.routers.locations import router as locations_router
from app.routers.predictions import router as predictions_router
from app.routers.impact import router as impact_router
from app.routers.alerts import router as alerts_router
from app.routers.copernicus import router as copernicus_router

__all__ = [
    "locations_router",
    "predictions_router",
    "impact_router",
    "alerts_router",
    "copernicus_router",
]
