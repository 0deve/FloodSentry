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
from app.config import get_settings

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
        "current": "temperature_2m",
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
    current = data.get("current", {})
    precip = hourly.get("precipitation", [0.0])
    soil_m = hourly.get("soil_moisture_0_to_1cm", [0.0])
    temp = hourly.get("temperature_2m", [0.0])
    current_temp = current.get("temperature_2m", 0.0)

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
        "current_temp": current_temp,
    }


# ---------------------------------------------------------------------------
# NDWI simulation
# (Replace with real Sentinel Hub API call when credentials are available)
# ---------------------------------------------------------------------------

def _simulate_ndwi(rainfall_mm: float, soil_moisture: float) -> float:
    """Simulate NDWI from rainfall + soil moisture proxies.

    Used as fallback when Sentinel Hub API is unavailable.
    """
    base = -0.3 + (soil_moisture * 0.5)
    rain_effect = min(rainfall_mm / 100.0, 0.5)
    ndwi = round(base + rain_effect, 4)
    return max(-1.0, min(1.0, ndwi))

# ---------------------------------------------------------------------------
# Real Sentinel Hub Integration (Copernicus Data Space Ecosystem)
# ---------------------------------------------------------------------------

_SH_TOKEN: str | None = None
_SH_TOKEN_EXPIRES: float = 0.0

async def _get_sh_token() -> str | None:
    """Get OAuth token from Copernicus Data Space Ecosystem."""
    global _SH_TOKEN, _SH_TOKEN_EXPIRES
    import time
    if _SH_TOKEN and time.time() < _SH_TOKEN_EXPIRES:
        return _SH_TOKEN

    settings = get_settings()
    if not settings.SENTINEL_HUB_CLIENT_ID or not settings.SENTINEL_HUB_CLIENT_SECRET:
        return None

    auth_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.SENTINEL_HUB_CLIENT_ID,
        "client_secret": settings.SENTINEL_HUB_CLIENT_SECRET,
    }
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(auth_url, data=data)
            resp.raise_for_status()
            js = resp.json()
            _SH_TOKEN = js.get("access_token")
            # Usually expires in 3600s, subtract 60s for safety buffer
            expires_in = js.get("expires_in", 3600)
            _SH_TOKEN_EXPIRES = time.time() + expires_in - 60
            return _SH_TOKEN
    except Exception as exc:
        logger.warning("Failed to get Sentinel Hub Token: %s", exc)
        return None

async def _fetch_real_ndwi(bbox: BBox) -> float:
    """Fetch real NDWI from Sentinel Hub Statistical API.

    Uses the CDSE Statistical API which correctly returns JSON statistics
    (mean, stdev, etc.) instead of raster data.
    Docs: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Statistical.html
    """
    token = await _get_sh_token()
    if not token:
        raise ValueError("No valid Sentinel Hub token.")

    from datetime import date, timedelta
    today = date.today()
    date_from = (today - timedelta(days=30)).isoformat() + "T00:00:00Z"
    date_to = today.isoformat() + "T23:59:59Z"

    # Statistical API evalscript — outputs NDWI as a band statistic
    evalscript = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B03", "B08", "SCL"], units: "DN" }],
    output: [
      { id: "ndwi", bands: 1, sampleType: "FLOAT32" }
    ]
  };
}
function evaluatePixel(samples) {
  // Exclude clouds (SCL 8,9,10) and no-data (0,1)
  let scl = samples.SCL;
  if ([0, 1, 8, 9, 10].includes(scl)) return { ndwi: [NaN] };
  let g = samples.B03;
  let nir = samples.B08;
  let ndwi = (g - nir) / (g + nir + 1e-10);
  return { ndwi: [ndwi] };
}"""

    payload = {
        "input": {
            "bounds": {
                "bbox": [bbox.min_lon, bbox.min_lat, bbox.max_lon, bbox.max_lat],
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {"from": date_from, "to": date_to},
                    "maxCloudCoverage": 80,
                    "mosaickingOrder": "leastCC"
                }
            }]
        },
        "aggregation": {
            "timeRange": {"from": date_from, "to": date_to},
            "aggregationInterval": {"of": "P30D"},
            "evalscript": evalscript,
            "resx": 0.01,
            "resy": 0.01
        },
        "calculations": {
            "default": {"histograms": {"default": {"nBins": 5, "lowEdge": -1.0, "highEdge": 1.0}}}
        }
    }

    stats_url = "https://sh.dataspace.copernicus.eu/api/v1/statistics"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(stats_url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    # Navigate the Statistical API response structure
    intervals = data.get("data", [])
    if not intervals:
        raise ValueError("No statistical data returned from Sentinel Hub")

    # Take the most recent interval's mean NDWI
    outputs = intervals[-1].get("outputs", {})
    ndwi_output = outputs.get("ndwi", {})
    bands = ndwi_output.get("bands", {})
    b0 = bands.get("B0", {})
    stats = b0.get("stats", {})
    mean_ndwi = stats.get("mean")

    if mean_ndwi is None:
        raise ValueError("No mean NDWI in Statistical API response")

    return round(float(mean_ndwi), 4)


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

        Uses real Sentinel Hub Process API if credentials are provided.
        Falls back to ERA5 simulation on failure.
        """
        source_name = "sentinel-2-l2a"
        try:
            ndwi_val = await _fetch_real_ndwi(bbox)
            logger.info("Successfully fetched real NDWI for %s: %.4f", nuts_id, ndwi_val)
        except Exception as exc:
            # Silence the loud 400 Bad Request error if bbox is too large or token invalid
            logger.debug("Sentinel Hub NDWI skipped for %s — falling back to simulation.", nuts_id)
            sm = await self.get_soil_moisture(nuts_id, bbox)
            ndwi_val = _simulate_ndwi(sm.rainfall_mm_48h, sm.soil_moisture_index)
            source_name = "sentinel-2-simulated"

        return NDWIResult(
            nuts_id=nuts_id,
            bbox=bbox,
            ndwi=ndwi_val,
            cloud_cover_pct=0.0,
            source=source_name,
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
