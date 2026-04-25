"""FloodSentry — Proactive Flood Risk Monitoring System.

CASSINI Hackathon 'EU Space for Water' — Challenge #3: Disaster Risk Monitoring
FastAPI application entry point.
"""

from contextlib import asynccontextmanager

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
    copernicus_router,
    ml_router,
    simulator_router,
)
from app.services.live_refresh import startup_seed_and_refresh, refresh_predictions
from app.database import SessionLocal

import logging
logger = logging.getLogger(__name__)

settings = get_settings()


# ── Lifespan: seed DB + fetch live satellite data on startup ──────────────────

import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: seed static data + start background fetch for Copernicus data."""
    logger.info("🚀 FloodSentry starting up...")
    
    # Run the long data fetch process in the background
    # so the server can accept requests immediately.
    asyncio.create_task(_background_startup_refresh())
    
    yield
    logger.info("FloodSentry shutting down.")

async def _background_startup_refresh():
    try:
        await startup_seed_and_refresh()
        logger.info("✅ Background startup complete — all regions populated with live data.")
    except Exception as exc:
        logger.error("⚠️  Background startup refresh failed: %s — app will serve empty data.", exc)


# ── App ───────────────────────────────────────────────────────────────────────

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
    lifespan=lifespan,
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
app.include_router(copernicus_router)
app.include_router(ml_router)
app.include_router(simulator_router)


# ── Core endpoints ────────────────────────────────────────────────────────────

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


@app.post("/api/v1/refresh")
async def manual_refresh(bad_weather: bool = False):
    """Manually trigger a live Copernicus data refresh.
    Defaults to Romania only for speed, unless otherwise specified.
    """
    db = SessionLocal()
    try:
        # Manual refreshes (buttons) only update Romania to keep it fast (<1s)
        result = await refresh_predictions(db, bad_weather=bad_weather, romania_only=True)
        return result
    finally:
        db.close()
