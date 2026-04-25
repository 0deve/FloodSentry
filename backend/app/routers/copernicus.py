"""Copernicus pipeline router — exposes Task 4 services via FastAPI.

Endpoints
---------
GET  /api/v1/copernicus/{nuts_id}/soil-moisture
GET  /api/v1/copernicus/{nuts_id}/ndwi
GET  /api/v1/copernicus/{nuts_id}/snow-cover
GET  /api/v1/copernicus/{nuts_id}/bundle
GET  /api/v1/ems/summary
GET  /api/v1/ems/samples
GET  /api/v1/hydro/summary
GET  /api/v1/hydro/{nuts_id}/downstream
GET  /api/v1/hydro/{nuts_id}/propagate
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.services.copernicus import BBox, CopernicusService
from app.services.ems_ground_truth import EMSGroundTruthService
from app.services.hydro_network import HydroNetworkService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Copernicus Pipeline"])

# ---------------------------------------------------------------------------
# Dependency singletons (one instance per app lifetime is fine for demo)
# ---------------------------------------------------------------------------

_copernicus_svc = CopernicusService()
_ems_svc = EMSGroundTruthService()
_hydro_svc = HydroNetworkService()


def get_copernicus() -> CopernicusService:
    return _copernicus_svc


def get_ems() -> EMSGroundTruthService:
    return _ems_svc


def get_hydro() -> HydroNetworkService:
    return _hydro_svc


# ---------------------------------------------------------------------------
# Shared helper — parse bbox query params
# ---------------------------------------------------------------------------


def _parse_bbox(
    min_lon: float = Query(27.5, description="Bounding box minimum longitude"),
    min_lat: float = Query(45.2, description="Bounding box minimum latitude"),
    max_lon: float = Query(28.2, description="Bounding box maximum longitude"),
    max_lat: float = Query(46.0, description="Bounding box maximum latitude"),
) -> BBox:
    return BBox(min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat)


# ---------------------------------------------------------------------------
# Copernicus endpoints
# ---------------------------------------------------------------------------


@router.get("/copernicus/{nuts_id}/soil-moisture")
async def get_soil_moisture(
    nuts_id: str,
    bbox: BBox = Depends(_parse_bbox),
    svc: CopernicusService = Depends(get_copernicus),
):
    """Fetch soil moisture index and 48-h rainfall for a NUTS region.

    Data source: Open-Meteo ERA5 reanalysis (Sentinel-1 SAR proxy).
    """
    result = await svc.get_soil_moisture(nuts_id, bbox)
    return {
        "nuts_id": result.nuts_id,
        "soil_moisture_index": result.soil_moisture_index,
        "rainfall_mm_48h": result.rainfall_mm_48h,
        "source": result.source,
        "fetched_at": result.fetched_at.isoformat(),
    }


@router.get("/copernicus/{nuts_id}/ndwi")
async def get_ndwi(
    nuts_id: str,
    bbox: BBox = Depends(_parse_bbox),
    svc: CopernicusService = Depends(get_copernicus),
):
    """Fetch NDWI (Normalized Difference Water Index) for a NUTS region.

    Positive values indicate surface-water presence.
    """
    result = await svc.get_ndwi(nuts_id, bbox)
    return {
        "nuts_id": result.nuts_id,
        "ndwi": result.ndwi,
        "cloud_cover_pct": result.cloud_cover_pct,
        "source": result.source,
        "fetched_at": result.fetched_at.isoformat(),
    }


@router.get("/copernicus/{nuts_id}/snow-cover")
async def get_snow_cover(
    nuts_id: str,
    bbox: BBox = Depends(_parse_bbox),
    svc: CopernicusService = Depends(get_copernicus),
):
    """Fetch Fractional Snow Cover and evaluate snowmelt flood risk.

    Multi-hazard trigger: FSC > 30 % AND ΔT > +10 °C in 48 h.
    """
    result = await svc.get_snow_cover(nuts_id, bbox)
    return {
        "nuts_id": result.nuts_id,
        "fsc_pct": result.fsc,
        "snowmelt_flood_risk": result.snowmelt_flood_risk,
        "trigger_reason": result.trigger_reason,
        "source": result.source,
        "fetched_at": result.fetched_at.isoformat(),
    }


@router.get("/copernicus/{nuts_id}/bundle")
async def get_copernicus_bundle(
    nuts_id: str,
    bbox: BBox = Depends(_parse_bbox),
    svc: CopernicusService = Depends(get_copernicus),
):
    """Fetch all Copernicus features (soil moisture + NDWI + snow cover) concurrently.

    Returns the full feature vector ready to be consumed by the ML engine.
    """
    bundle = await svc.fetch_all(nuts_id, bbox)
    return {
        "nuts_id": bundle.nuts_id,
        "feature_vector": bundle.feature_vector,
        "snow_cover": {
            "fsc_pct": bundle.snow_cover.fsc,
            "snowmelt_flood_risk": bundle.snow_cover.snowmelt_flood_risk,
            "trigger_reason": bundle.snow_cover.trigger_reason,
        },
        "fetched_at": bundle.fetched_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# EMS Ground Truth endpoints
# ---------------------------------------------------------------------------


@router.get("/ems/summary")
def ems_summary(svc: EMSGroundTruthService = Depends(get_ems)):
    """Return a summary of the EMS ground-truth activation dataset."""
    s = svc.summary()
    # Convert date objects to strings for JSON serialisation
    dr = s.get("date_range", {})
    if dr.get("earliest"):
        dr["earliest"] = dr["earliest"].isoformat()
    if dr.get("latest"):
        dr["latest"] = dr["latest"].isoformat()
    return s


@router.get("/ems/samples")
def ems_samples(
    nuts_id: str | None = None,
    hazard_type: str | None = None,
    svc: EMSGroundTruthService = Depends(get_ems),
):
    """Return labelled training samples from EMS activation records.

    Optionally filter by NUTS-3 ID and/or hazard type
    (``fluvial`` | ``pluvial`` | ``snowmelt``).
    """
    nuts_ids = [nuts_id] if nuts_id else None
    samples = svc.get_labelled_samples(nuts_ids=nuts_ids, hazard_type=hazard_type)
    return [s.to_dict() for s in samples]


# ---------------------------------------------------------------------------
# Hydrographic network endpoints
# ---------------------------------------------------------------------------


@router.get("/hydro/summary")
def hydro_summary(svc: HydroNetworkService = Depends(get_hydro)):
    """Return a summary of the loaded hydrographic river network graph."""
    return svc.summary()


@router.get("/hydro/{nuts_id}/downstream")
def hydro_downstream(
    nuts_id: str,
    svc: HydroNetworkService = Depends(get_hydro),
):
    """Trace downstream river paths from all reaches within a NUTS region.

    Returns ordered NUTS regions the water flows through from this region
    to the river outlet (useful for downstream alert propagation).
    """
    reaches = svc.get_nuts_reaches(nuts_id)
    if not reaches:
        raise HTTPException(
            status_code=404,
            detail=f"No river reaches found for NUTS region '{nuts_id}'",
        )

    results = []
    for seg in reaches:
        path = svc.get_downstream_path(seg.reach_id)
        if path:
            results.append(
                {
                    "reach_id": path.origin_reach_id,
                    "downstream_nuts_ids": path.nuts_ids,
                    "total_length_km": path.total_length_km,
                }
            )

    return {"nuts_id": nuts_id, "downstream_paths": results}


@router.get("/hydro/{nuts_id}/propagate")
def hydro_propagate(
    nuts_id: str,
    risk_score: float = Query(
        75.0, ge=0, le=100, description="Upstream risk score (0-100)"
    ),
    svc: HydroNetworkService = Depends(get_hydro),
):
    """Propagate an upstream risk score to downstream NUTS regions.

    Uses an exponential attenuation model (20 % decay per river hop).
    This implements the GNN-lite structural prior described in the plan.
    """
    propagated = svc.get_upstream_risk_propagation(nuts_id, risk_score)
    if not propagated:
        return {
            "origin_nuts_id": nuts_id,
            "propagated_risks": {},
            "message": "No downstream regions found or no reaches in this NUTS region.",
        }
    return {
        "origin_nuts_id": nuts_id,
        "origin_risk_score": risk_score,
        "propagated_risks": propagated,
    }
