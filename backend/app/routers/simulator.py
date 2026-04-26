"""Simulator Router — Time-stepped hydrologic risk propagation.

Provides a time-slider-driven simulation endpoint.
Instead of a single "Simulate" button, the frontend uses a timeline
slider with "Play" to animate precipitation entering upstream regions
and risk growing gradually downstream.

Endpoints
---------
GET /api/v1/simulator/timeline
    Returns a list of time-steps (0h → 48h) with risk scores per region.
    The frontend animates through these to show the flood wave.

GET /api/v1/simulator/step
    Returns risk state at a single time step (for slider scrubbing).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/simulator", tags=["Simulator"])


from app.services.eu_regions import NUTS_REGIONS

# Total simulation duration in hours (7 days)
TOTAL_HOURS = 168
# Number of time steps (every 12 hours)
NUM_STEPS = 14


# ── Response Schemas ────────────────────────────────────────────


class RegionState(BaseModel):
    """State of a single region at a given time step."""

    nuts_id: str
    name: str
    lat: float
    lon: float
    risk_score: float = Field(ge=0, le=100)
    alert_level: str
    wave_active: bool = False
    rainfall_mm: float = 0.0
    description: str = ""


class TimeStep(BaseModel):
    """A single frame in the simulation timeline."""

    step: int
    hour: float
    label: str
    regions: list[RegionState]


class SimulationTimeline(BaseModel):
    """Complete simulation timeline for animation."""

    scenario: str
    total_steps: int
    total_hours: float
    rainfall_mm: float
    month: int
    steps: list[TimeStep]
    computed_at: str


# ── Risk Calculation ────────────────────────────────────────────


def _risk_at_time_front(
    lon: float,
    current_hour: float,
    rainfall_mm: float,
) -> tuple[float, float]:
    """Calculate risk and rainfall based on storm passing West to East."""
    # Storm moves from longitude -10 to +30 over TOTAL_HOURS
    storm_center_lon = -10.0 + (40.0 * (current_hour / TOTAL_HOURS))
    
    # Distance to storm (longitude degrees)
    dist = abs(lon - storm_center_lon)
    
    # If storm is nearby (within 5 degrees), heavy rain!
    rain = 0.0
    if dist < 5.0:
        # Peak rain at center
        rain = rainfall_mm * (1.0 - (dist / 5.0))
        
    # Risk builds up when storm passes, then decays
    # Peak risk is slightly after the storm passes
    risk_factor = 0.0
    if storm_center_lon >= lon - 2:
        # Storm has reached or passed
        # Decay over time after it passes (each degree is roughly 168/40 = 4.2 hours)
        time_since_storm = current_hour - ((lon + 10) / 40.0 * TOTAL_HOURS)
        if time_since_storm > 0:
            risk_factor = math.exp(-0.02 * time_since_storm)
        else:
            # Building up
            risk_factor = 0.5 * math.exp(0.1 * time_since_storm)
            
    # Base risk is very low
    risk = 2.0 + (risk_factor * 85.0 * (rainfall_mm / 150.0))
    return min(100.0, max(0.0, risk)), rain


def _risk_at_time_clusters(
    lat: float,
    lon: float,
    current_hour: float,
    rainfall_mm: float,
    clusters: list[dict],
) -> tuple[float, float]:
    """Calculate risk and rainfall based on random storm clusters."""
    total_rain = 0.0
    max_risk_factor = 0.0

    for c in clusters:
        # Distance to this cluster center
        dist = math.hypot(lat - c["lat"], lon - c["lon"])
        
        # Is it currently raining from this cluster?
        if c["start_hour"] <= current_hour <= c["start_hour"] + c["duration"] and dist < c["radius"]:
            intensity = 1.0 - (dist / c["radius"])
            time_progress = (current_hour - c["start_hour"]) / c["duration"]
            # Parabola intensity over time: 0 -> 1 -> 0
            time_intensity = 4.0 * time_progress * (1.0 - time_progress)
            total_rain += rainfall_mm * intensity * time_intensity
            
        # Risk factor builds up after rain starts
        if current_hour > c["start_hour"] and dist < c["radius"]:
            time_since_start = current_hour - c["start_hour"]
            if time_since_start <= c["duration"]:
                # Linearly build up while storm is active
                risk_factor = (time_since_start / c["duration"]) * (1.0 - dist / c["radius"])
            else:
                # Decay after storm passes
                time_since_end = current_hour - (c["start_hour"] + c["duration"])
                risk_factor = (1.0 - dist / c["radius"]) * math.exp(-0.03 * time_since_end)
            max_risk_factor = max(max_risk_factor, risk_factor)

    risk = 2.0 + (max_risk_factor * 85.0 * (rainfall_mm / 150.0))
    return min(100.0, max(0.0, risk)), total_rain


def _alert_level(risk: float) -> str:
    if risk >= 75:
        return "emergency"
    if risk >= 60:
        return "critical"
    if risk >= 30:
        return "warning"
    return "info"


def _step_description(regions: list[RegionState], current_hour: float) -> str:
    active = [r for r in regions if r.risk_score > 60]
    if not active:
        return f"T+{current_hour:.0f}h: Storm is forming. No major alerts."
    names = [r.name for r in active[:3]]
    return f"T+{current_hour:.0f}h: Red Alert! Flooding in {', '.join(names)}. Critical water levels."


# ── Endpoints ───────────────────────────────────────────────────


@router.get("/timeline", response_model=SimulationTimeline)
def get_simulation_timeline(
    rainfall_mm: float = Query(
        150.0,
        ge=0.0,
        le=400.0,
        description="Rainfall at the origin (mm). Controls flood severity.",
    ),
    month: int = Query(
        7,
        ge=1,
        le=12,
        description="Month for seasonal context.",
    ),
    storm_type: str = Query(
        "front",
        description="Type of storm: 'front' (West->East) or 'clusters' (Random).",
    ),
):
    """Generate a complete 7-day simulation timeline for all of Europe.
    Supports either a moving front or random storm clusters."""

    import random
    
    steps: list[TimeStep] = []
    hours_per_step = TOTAL_HOURS / NUM_STEPS

    clusters = []
    if storm_type == "clusters":
        # Generate 6 random storm clusters across Europe
        rng = random.Random(42) # Fixed seed for consistent timeline generation within the same request
        for _ in range(6):
            clusters.append({
                "lon": rng.uniform(-5.0, 25.0),
                "lat": rng.uniform(40.0, 55.0),
                "start_hour": rng.uniform(0, TOTAL_HOURS - 48),
                "duration": rng.uniform(24, 72),
                "radius": rng.uniform(3.0, 7.0),
            })

    for i in range(NUM_STEPS + 1):
        current_hour = i * hours_per_step
        regions: list[RegionState] = []

        for node in NUTS_REGIONS:
            if storm_type == "clusters":
                risk, rain = _risk_at_time_clusters(
                    node["latitude"],
                    node["longitude"],
                    current_hour,
                    rainfall_mm,
                    clusters
                )
            else:
                risk, rain = _risk_at_time_front(
                    node["longitude"],
                    current_hour,
                    rainfall_mm,
                )

            level = _alert_level(risk)
            wave_active = risk > 30 and rain > 10

            regions.append(
                RegionState(
                    nuts_id=node["nuts_id"],
                    name=node["name"],
                    lat=node["latitude"],
                    lon=node["longitude"],
                    risk_score=round(risk, 1),
                    alert_level=level,
                    wave_active=wave_active,
                    rainfall_mm=round(rain, 1),
                )
            )

        # Sort descending by risk so frontend can grab top 5 easily
        regions.sort(key=lambda r: r.risk_score, reverse=True)
        
        # Populate description
        desc = _step_description(regions, current_hour)
        for r in regions:
            r.description = desc

        label = f"Day {(current_hour // 24) + 1} (T+{current_hour:.0f}h)"
        if current_hour == 0:
            label = "Day 1 (Start)"
        elif current_hour >= TOTAL_HOURS:
            label = f"Day 7 (End)"

        steps.append(
            TimeStep(
                step=i,
                hour=current_hour,
                label=label,
                regions=regions,
            )
        )

    scenario_name = "European Storm: West → East" if storm_type == "front" else "Local Storms (Random Clusters)"

    return SimulationTimeline(
        scenario=f"{scenario_name} (7 Days)",
        total_steps=NUM_STEPS + 1,
        total_hours=TOTAL_HOURS,
        rainfall_mm=rainfall_mm,
        month=month,
        steps=steps,
        computed_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/step", response_model=TimeStep)
def get_simulation_step(
    step: int = Query(0, ge=0, le=NUM_STEPS, description="Time step index."),
    rainfall_mm: float = Query(150.0, ge=0.0, le=400.0),
    month: int = Query(7, ge=1, le=12),
):
    """Get the simulation state at a single time step.

    Used for slider scrubbing — the frontend can request individual
    frames without loading the full timeline.
    """
    timeline = get_simulation_timeline(rainfall_mm=rainfall_mm, month=month)
    if step >= len(timeline.steps):
        step = len(timeline.steps) - 1
    return timeline.steps[step]
