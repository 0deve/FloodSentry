"""FloodSentry — Proactive Flood Risk Monitoring System.

CASSINI Hackathon 'EU Space for Water' — Challenge #3: Disaster Risk Monitoring
FastAPI application entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Base, engine

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
