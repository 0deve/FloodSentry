"""FloodSentry — Proactive Flood Risk Monitoring System.

CASSINI Hackathon 'EU Space for Water' — Challenge #3: Disaster Risk Monitoring
FastAPI application entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Base, engine

# Import models so they register with Base.metadata before create_all
from app.models import Location, CriticalInfrastructure, FloodPrediction, Alert  # noqa: F401
from app.routers import (
    locations_router,
    predictions_router,
    impact_router,
    alerts_router,
)

settings = get_settings()

# Create all database tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Proactive flood risk monitoring system integrating Copernicus "
        "and Galileo space data with ML-driven risk assessment for "
        "pan-European NUTS regions."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(locations_router)
app.include_router(predictions_router)
app.include_router(impact_router)
app.include_router(alerts_router)


@app.get("/")
async def root():
    """Health check / welcome endpoint."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "operational",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """Detailed health check endpoint."""
    return {
        "status": "healthy",
        "database": "connected",
        "version": settings.APP_VERSION,
    }
