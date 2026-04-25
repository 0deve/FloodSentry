"""ML Engine Router — Task 5 API endpoints.

Exposes the XGBoost flood classifier and GNN-lite risk propagator via
FastAPI.  All heavy model objects are instantiated once at module import
time (singleton pattern) so that the XGBoost training step runs only
once on server startup.

Endpoints
---------
POST /api/v1/ml/predict
    Run XGBoost inference for a single NUTS region.

POST /api/v1/ml/predict/batch
    Run inference for multiple NUTS regions in one call.

POST /api/v1/ml/propagate
    Propagate a risk wave downstream from a NUTS origin node.

GET  /api/v1/ml/propagate/demo
    Demo scenario: Tecuci → Galați → Danube with a slider-controlled
    rainfall input.  Mirrors the Step 3 fallback from the task plan.

GET  /api/v1/ml/model/info
    Return XGBoost model metadata and feature importances.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.ml.flood_classifier import FloodClassifier, FloodFeatures
from app.ml.risk_propagator import RiskPropagator
from app.services.hydro_network import HydroNetworkService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ml", tags=["ML Engine"])

# ---------------------------------------------------------------------------
# Singletons — instantiated once on module import (training happens here)
# ---------------------------------------------------------------------------

_classifier = FloodClassifier()
_hydro_svc = HydroNetworkService()
_propagator = RiskPropagator(hydro_svc=_hydro_svc)
_demo_propagator = RiskPropagator(hydro_svc=None)   # uses hard-coded demo corridor


def get_classifier() -> FloodClassifier:
    return _classifier


def get_propagator() -> RiskPropagator:
    return _propagator


def get_demo_propagator() -> RiskPropagator:
    return _demo_propagator


# ---------------------------------------------------------------------------
# Pydantic request / response schemas
# ---------------------------------------------------------------------------


class PredictRequest(BaseModel):
    """Input for single-region flood prediction."""

    nuts_id: str = Field(..., description="NUTS-3 region code (e.g. 'RO224')")
    month: int = Field(
        default_factory=lambda: datetime.now(timezone.utc).month,
        ge=1,
        le=12,
        description="Calendar month (1-12). Defaults to current month.",
    )
    # Satellite features
    soil_moisture: float = Field(0.30, ge=0.0, le=1.0, description="Soil moisture index 0-1")
    ndwi: float = Field(-0.2, ge=-1.0, le=1.0, description="Normalized Difference Water Index")
    ndvi: float = Field(0.50, ge=0.0, le=1.0, description="Normalized Difference Vegetation Index")
    snow_cover: float = Field(0.0, ge=0.0, le=1.0, description="Fractional Snow Cover 0-1 (FSC/100)")
    # Meteo features
    rainfall_24h: float = Field(0.0, ge=0.0, description="Rainfall in last 24 h (mm)")
    temp_trend: float = Field(0.0, description="Temperature trend ΔT °C over 48 h")
    # Geographic features
    elevation: float = Field(150.0, ge=0.0, description="Mean elevation of region (m)")
    slope: float = Field(2.0, ge=0.0, description="Mean terrain slope (°)")
    # Graph feature
    upstream_risk: float = Field(0.0, ge=0.0, le=100.0, description="Propagated upstream risk score 0-100")

    model_config = {"json_schema_extra": {
        "example": {
            "nuts_id": "RO224",
            "month": 7,
            "soil_moisture": 0.72,
            "ndwi": 0.18,
            "ndvi": 0.45,
            "snow_cover": 0.0,
            "rainfall_24h": 85.0,
            "temp_trend": 2.5,
            "elevation": 45.0,
            "slope": 1.2,
            "upstream_risk": 68.0,
        }
    }}


class PropagateRequest(BaseModel):
    """Input for risk wave propagation."""

    origin_nuts_id: str = Field(..., description="Source NUTS-3 region")
    initial_risk: float = Field(..., ge=0.0, le=100.0, description="Risk score at origin (0-100)")
    rainfall_override_mm: float | None = Field(
        None, ge=0.0, description="Rainfall override to boost initial risk (mm)"
    )
    month: int | None = Field(
        None, ge=1, le=12, description="Month for seasonal boost. Defaults to current."
    )

    model_config = {"json_schema_extra": {
        "example": {
            "origin_nuts_id": "RO216",
            "initial_risk": 85.0,
            "rainfall_override_mm": 200.0,
            "month": 7,
        }
    }}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/predict")
def predict_single(
    request: PredictRequest,
    clf: FloodClassifier = Depends(get_classifier),
):
    """Run XGBoost flood probability prediction for a single NUTS region.

    Returns `risk_score` (0-100), `hazard_type` (fluvial/pluvial/snowmelt),
    `flood_probability` (0-1), and the dominant trigger feature.
    """
    features = FloodFeatures(
        nuts_id=request.nuts_id,
        month=request.month,
        soil_moisture=request.soil_moisture,
        ndwi=request.ndwi,
        ndvi=request.ndvi,
        snow_cover=request.snow_cover,
        rainfall_24h=request.rainfall_24h,
        temp_trend=request.temp_trend,
        elevation=request.elevation,
        slope=request.slope,
        upstream_risk=request.upstream_risk,
    )

    result = clf.predict(features)
    return {
        "nuts_id": result.nuts_id,
        "risk_score": result.risk_score,
        "flood_probability": result.flood_probability,
        "hazard_type": result.hazard_type,
        "dominant_feature": result.dominant_feature,
        "model_version": result.model_version,
        "features_used": result.features_used,
        "predicted_at": result.predicted_at,
    }


@router.post("/predict/batch")
def predict_batch(
    requests: list[PredictRequest],
    clf: FloodClassifier = Depends(get_classifier),
):
    """Run XGBoost flood prediction for multiple NUTS regions.

    Accepts a JSON array of region feature vectors and returns a list of
    prediction results ordered by descending risk score.
    """
    if not requests:
        raise HTTPException(status_code=400, detail="Empty batch — provide at least one region.")
    if len(requests) > 100:
        raise HTTPException(status_code=400, detail="Batch too large — maximum 100 regions.")

    features_list = [
        FloodFeatures(
            nuts_id=r.nuts_id,
            month=r.month,
            soil_moisture=r.soil_moisture,
            ndwi=r.ndwi,
            ndvi=r.ndvi,
            snow_cover=r.snow_cover,
            rainfall_24h=r.rainfall_24h,
            temp_trend=r.temp_trend,
            elevation=r.elevation,
            slope=r.slope,
            upstream_risk=r.upstream_risk,
        )
        for r in requests
    ]

    results = clf.predict_batch(features_list)
    results.sort(key=lambda r: r.risk_score, reverse=True)

    return [
        {
            "nuts_id": r.nuts_id,
            "risk_score": r.risk_score,
            "flood_probability": r.flood_probability,
            "hazard_type": r.hazard_type,
            "dominant_feature": r.dominant_feature,
            "model_version": r.model_version,
            "predicted_at": r.predicted_at,
        }
        for r in results
    ]


@router.post("/propagate")
def propagate_risk(
    request: PropagateRequest,
    propagator: RiskPropagator = Depends(get_propagator),
):
    """Propagate a flood risk wave downstream through the hydrographic network.

    Uses the GNN-lite algorithm (exponential decay + seasonal boost) on the
    HydroSHEDS / EU-Hydro directed graph.

    The response includes:
    - `waves`: downstream NUTS regions sorted by travel time
    - `delay_hours`: estimated time for the risk wave to arrive
    - `hops`: number of river segments traversed
    - `seasonal_boost_applied`: True if spring/autumn amplification was used
    """
    result = propagator.propagate(
        origin_nuts_id=request.origin_nuts_id,
        initial_risk=request.initial_risk,
        rainfall_override_mm=request.rainfall_override_mm,
        month=request.month,
    )
    return result.to_dict()


@router.get("/propagate/demo")
def propagate_demo(
    rainfall_mm: float = Query(
        100.0,
        ge=0.0,
        le=400.0,
        description="Rainfall at Tecuci (mm). Simulates demo slider.",
    ),
    month: int = Query(
        default_factory=lambda: datetime.now(timezone.utc).month,
        ge=1,
        le=12,
        description="Month for seasonal boost.",
    ),
    demo_prop: RiskPropagator = Depends(get_demo_propagator),
):
    """Demo scenario: Tecuci → Liești → Galați → Danube risk propagation.

    This endpoint implements the Step 3 fallback demo from Task 5:
    set rainfall at Tecuci (upstream) via the `rainfall_mm` slider and
    watch the risk wave propagate downstream to Galați and the Danube.

    Returns a time-ordered list of downstream regions with their predicted
    risk scores and arrival delays — perfect for animating on the map.
    """
    # Derive initial risk from rainfall (domain heuristic for demo)
    base_risk = min(100.0, 20.0 + rainfall_mm * 0.40)

    result = demo_prop.propagate(
        origin_nuts_id="RO216",
        initial_risk=base_risk,
        rainfall_override_mm=rainfall_mm,
        month=month,
    )

    return {
        "scenario": "Tecuci → Galați → Danube corridor",
        "inputs": {
            "rainfall_mm_at_tecuci": rainfall_mm,
            "month": month,
        },
        "origin": {
            "nuts_id": "RO216",
            "name": "Vaslui / Tecuci",
            "initial_risk": result.initial_risk,
        },
        "downstream_waves": [w.to_dict() for w in result.waves],
        "summary": {
            "total_affected_nuts": result.total_affected_nuts,
            "max_downstream_risk": result.max_downstream_risk,
            "seasonal_boost": result.seasonal_boost,
        },
        "computed_at": result.computed_at,
    }


@router.get("/model/info")
def model_info(clf: FloodClassifier = Depends(get_classifier)):
    """Return XGBoost model metadata, feature importances, and configuration.

    Useful for the frontend's "Model Info" panel and for hackathon judges
    inspecting the ML pipeline.
    """
    info = clf.model_info()
    prop_info = _propagator.info()
    return {
        "classifier": info,
        "propagator": prop_info,
    }
