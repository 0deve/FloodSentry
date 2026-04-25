"""Copernicus Data Pipeline — Multi-Hazard Satellite Data Service.

Integrates three Copernicus/EU Space data streams:
  1. Soil Moisture  — Sentinel-1 SAR proxy via Open-Meteo ERA5
  2. NDWI           — Sentinel-2 Normalized Difference Water Index (simulated)
  3. Snow Cover     — Sentinel-3 / CLMS Fractional Snow Cover (FSC)

Multi-hazard trigger:
  • snowmelt_flood_risk → FSC > 30 % in mountain bbox AND ΔT > +10 °C in 48 h
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------

@dataclass
class BBox:
    """Geographic bounding-box (WGS-84)."""

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    @property
    def center(self) -> tuple[float, float]:
        return (
            (self.min_lat + self.max_lat) / 2,
            (self.min_lon + self.max_lon) / 2,
        )


@dataclass
class SoilMoistureResult:
    nuts_id: str
    bbox: BBox
    soil_moisture_index: float          # 0-1  (volumetric water content proxy)
    rainfall_mm_48h: float              # mm over the last 48 h
    source: str = "open-meteo-era5"
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class NDWIResult:
    nuts_id: str
    bbox: BBox
    ndwi: float                         # −1 to +1  (positive → water body)
    cloud_cover_pct: float              # 0-100
    source: str = "sentinel-2-simulated"
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SnowCoverResult:
    nuts_id: str
    bbox: BBox
    fsc: float                          # Fractional Snow Cover  0-100 %
    snowmelt_flood_risk: bool           # Multi-hazard trigger
    trigger_reason: str                 # Human-readable explanation
    source: str = "sentinel-3-clms-simulated"
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CopernicusBundle:
    """All satellite-derived features for a single NUTS region."""

    nuts_id: str
    bbox: BBox
    soil_moisture: SoilMoistureResult
    ndwi: NDWIResult
    snow_cover: SnowCoverResult
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Convenience accessors used by the ML pipeline
    @property
    def feature_vector(self) -> dict[str, float]:
        return {
            "rainfall_mm": self.soil_moisture.rainfall_mm_48h,
            "soil_moisture": self.soil_moisture.soil_moisture_index,
            "ndwi": self.ndwi.ndwi,
            "snow_water_equivalent": self.snow_cover.fsc / 100.0,
        }


# ---------------------------------------------------------------------------
# Open-Meteo helpers
# ---------------------------------------------------------------------------

_OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

# Variable codes (ERA5 reanalysis / forecast blend)
_HOURLY_VARS = [
    "precipitation",
    "soil_moisture_0_to_1cm",
    "temperature_2m",
    "snowfall",
]


async def _fetch_open_meteo(lat: float, lon: float) -> dict[str, Any]:
    """Fetch 48-hour hourly forecast from Open-Meteo (free, no auth)."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(_HOURLY_VARS),
        "forecast_days": 2,
        "timezone": "UTC",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_OPEN_METEO_BASE, params=params)
        resp.raise_for_status()
        return resp.json()


def _parse_open_meteo(data: dict[str, Any]) -> dict[str, float]:
    """Extract scalar summaries from the hourly time-series."""
    hourly = data.get("hourly", {})
    precip = hourly.get("precipitation", [0.0])
    soil_m = hourly.get("soil_moisture_0_to_1cm", [0.0])
    temp = hourly.get("temperature_2m", [0.0])

    # Safe defaults for missing values
    precip = [v or 0.0 for v in precip]
    soil_m = [v or 0.0 for v in soil_m]
    temp = [v or 0.0 for v in temp]

    rainfall_48h = sum(precip[:48])
    avg_soil = sum(soil_m[:48]) / max(len(soil_m[:48]), 1)

    # ΔT: difference between the max temperature in 25-48 h vs 0-24 h
    t_first_24 = max(temp[:24], default=0.0)
    t_next_24 = max(temp[24:48], default=0.0)
    delta_temp_48h = t_next_24 - t_first_24

    return {
        "rainfall_mm_48h": round(rainfall_48h, 2),
        "soil_moisture_index": round(avg_soil, 4),
        "delta_temp_48h": round(delta_temp_48h, 2),
    }


# ---------------------------------------------------------------------------
# NDWI simulation
# (Replace with real Sentinel Hub API call when credentials are available)
# ---------------------------------------------------------------------------

def _simulate_ndwi(rainfall_mm: float, soil_moisture: float) -> float:
    """Simulate NDWI from rainfall + soil moisture proxies.

    Real implementation would call Sentinel Hub Process API:
        POST https://services.sentinel-hub.com/api/v1/process
        evalscript: (B03 - B08) / (B03 + B08)

    Returns a value in [-1, 1].  Positive values indicate surface water.
    """
    base = -0.3 + (soil_moisture * 0.5)
    rain_effect = min(rainfall_mm / 100.0, 0.5)
    ndwi = round(base + rain_effect, 4)
    return max(-1.0, min(1.0, ndwi))


# ---------------------------------------------------------------------------
# FSC simulation
# (Replace with Copernicus CLMS HRSI product download when API is stable)
# ---------------------------------------------------------------------------

_MOUNTAIN_ELEV_THRESHOLD_M = 800   # treat bbox as "mountain" if mean elev > 800 m
_FSC_SNOWMELT_THRESHOLD = 30.0     # %
_DELTA_TEMP_SNOWMELT_THRESHOLD = 10.0  # °C in 48 h


def _simulate_fsc(lat: float, lon: float, rainfall_mm: float) -> float:
    """Estimate Fractional Snow Cover from latitude and season.

    Real implementation sources:
    • Copernicus Land Monitoring Service (CLMS) — HRSI FSC product
    • https://land.copernicus.eu/pan-european/biophysical-parameters/high-resolution-snow-and-ice-monitoring
    """
    month = datetime.now(timezone.utc).month
    winter = month in (12, 1, 2, 3)
    alpine = lat > 44.0  # rough Carpathian / Alpine threshold

    if winter and alpine:
        base_fsc = 55.0
    elif winter:
        base_fsc = 20.0
    elif alpine and month in (4, 11):
        base_fsc = 35.0
    else:
        base_fsc = 5.0

    # Heavy rain in spring melts snow faster → lower FSC reading
    melt_factor = max(0.0, rainfall_mm / 60.0) * 15.0
    return round(max(0.0, base_fsc - melt_factor), 2)


# ---------------------------------------------------------------------------
# Main service class
# ---------------------------------------------------------------------------


class CopernicusService:
    """Fetches and fuses Copernicus satellite-derived features for a NUTS bbox.

    Usage::

        svc = CopernicusService()
        bundle = await svc.fetch_all(nuts_id="RO224", bbox=BBox(27.5, 45.2, 28.2, 46.0))
    """

    # ------------------------------------------------------------------ #
    # Step 1 — Soil Moisture (Sentinel-1 SAR proxy via Open-Meteo ERA5)  #
    # ------------------------------------------------------------------ #

    async def get_soil_moisture(
        self, nuts_id: str, bbox: BBox
    ) -> SoilMoistureResult:
        """Return soil moisture index and 48-h rainfall for the given bbox.

        Data source: Open-Meteo ERA5 reanalysis (real-time, no authentication).
        Production upgrade: Replace with Sentinel Hub SAR backscatter call.
        """
        lat, lon = bbox.center
        logger.info("Fetching Open-Meteo ERA5 for NUTS %s (%.4f, %.4f)", nuts_id, lat, lon)

        try:
            raw = await _fetch_open_meteo(lat, lon)
            parsed = _parse_open_meteo(raw)
        except Exception as exc:
            logger.warning("Open-Meteo request failed for %s: %s — using fallback", nuts_id, exc)
            parsed = {"rainfall_mm_48h": 0.0, "soil_moisture_index": 0.2, "delta_temp_48h": 0.0}

        return SoilMoistureResult(
            nuts_id=nuts_id,
            bbox=bbox,
            soil_moisture_index=parsed["soil_moisture_index"],
            rainfall_mm_48h=parsed["rainfall_mm_48h"],
        )

    # ------------------------------------------------------------------ #
    # Step 1b — NDWI (Sentinel-2 optical)                                #
    # ------------------------------------------------------------------ #

    async def get_ndwi(self, nuts_id: str, bbox: BBox) -> NDWIResult:
        """Return NDWI for the given bbox.

        Currently simulated from ERA5 proxies. Production upgrade:
        POST to Sentinel Hub Process API with a McFeeters NDWI evalscript.
        Requires SENTINEL_HUB_CLIENT_ID / SECRET in .env.
        """
        # Re-use soil moisture fetch to avoid duplicate HTTP calls
        sm = await self.get_soil_moisture(nuts_id, bbox)
        ndwi_val = _simulate_ndwi(sm.rainfall_mm_48h, sm.soil_moisture_index)

        return NDWIResult(
            nuts_id=nuts_id,
            bbox=bbox,
            ndwi=ndwi_val,
            cloud_cover_pct=0.0,  # placeholder; real call returns actual cloud mask
        )

    # ------------------------------------------------------------------ #
    # Step 1 (Task 4) — Snowmelt Hazard (Sentinel-3 / CLMS FSC)          #
    # ------------------------------------------------------------------ #

    async def get_snow_cover(self, nuts_id: str, bbox: BBox) -> SnowCoverResult:
        """Return Fractional Snow Cover and evaluate snowmelt flood risk.

        Multi-hazard logic (per Task 4 spec):
          • FSC > 30 % (mountain snow pack present)
          • AND forecast ΔT > +10 °C in 48 h (rapid warm-up incoming)
          → Activates `snowmelt_flood_risk = True`

        Data source: Simulated from Open-Meteo + lat/season heuristics.
        Production upgrade: Copernicus CLMS HRSI FSC product via WCS/WMS.
        """
        lat, lon = bbox.center
        logger.info("Evaluating snow cover / snowmelt risk for NUTS %s", nuts_id)

        # Fetch weather forecast for delta_temp
        try:
            raw = await _fetch_open_meteo(lat, lon)
            parsed = _parse_open_meteo(raw)
            delta_temp = parsed["delta_temp_48h"]
            rainfall_mm = parsed["rainfall_mm_48h"]
        except Exception as exc:
            logger.warning("Open-Meteo failed for snow check %s: %s", nuts_id, exc)
            delta_temp = 0.0
            rainfall_mm = 0.0

        fsc = _simulate_fsc(lat, lon, rainfall_mm)

        trigger = fsc > _FSC_SNOWMELT_THRESHOLD and delta_temp > _DELTA_TEMP_SNOWMELT_THRESHOLD
        if trigger:
            reason = (
                f"FSC={fsc:.1f}% > {_FSC_SNOWMELT_THRESHOLD}% "
                f"AND dT48h={delta_temp:+.1f}C > +{_DELTA_TEMP_SNOWMELT_THRESHOLD}C"
            )
        elif fsc > _FSC_SNOWMELT_THRESHOLD:
            reason = f"High FSC={fsc:.1f}% but dT48h={delta_temp:+.1f}C below threshold"
        else:
            reason = f"Low FSC={fsc:.1f}% - snowmelt risk negligible"

        return SnowCoverResult(
            nuts_id=nuts_id,
            bbox=bbox,
            fsc=fsc,
            snowmelt_flood_risk=trigger,
            trigger_reason=reason,
        )

    # ------------------------------------------------------------------ #
    # Aggregate — fetch all features in parallel                          #
    # ------------------------------------------------------------------ #

    async def fetch_all(self, nuts_id: str, bbox: BBox) -> CopernicusBundle:
        """Fetch soil moisture, NDWI, and snow cover concurrently.

        Returns a :class:`CopernicusBundle` with a `.feature_vector` property
        ready to be consumed by the XGBoost / GNN prediction pipeline.
        """
        import asyncio

        sm_task = asyncio.create_task(self.get_soil_moisture(nuts_id, bbox))
        ndwi_task = asyncio.create_task(self.get_ndwi(nuts_id, bbox))
        snow_task = asyncio.create_task(self.get_snow_cover(nuts_id, bbox))

        sm, ndwi, snow = await asyncio.gather(sm_task, ndwi_task, snow_task)

        return CopernicusBundle(
            nuts_id=nuts_id,
            bbox=bbox,
            soil_moisture=sm,
            ndwi=ndwi,
            snow_cover=snow,
        )
