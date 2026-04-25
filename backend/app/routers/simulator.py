"""Simulator Router — Time-stepped hydrologic risk propagation.

Task 7, Step 4: Provides a time-slider-driven simulation endpoint.
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


# ── Demo Corridor ───────────────────────────────────────────────
# Hard-coded demo corridor: Tecuci → Liești → Galați → Danube
DEMO_CORRIDOR = [
    {
        "nuts_id": "RO216",
        "name": "Vaslui / Tecuci",
        "lat": 46.40,
        "lon": 27.73,
        "distance_km": 0,
        "delay_hours": 0,
    },
    {
        "nuts_id": "RO226",
        "name": "Vrancea / Focșani",
        "lat": 45.70,
        "lon": 27.18,
        "distance_km": 85,
        "delay_hours": 6,
    },
    {
        "nuts_id": "RO225",
        "name": "Buzău",
        "lat": 45.15,
        "lon": 26.83,
        "distance_km": 140,
        "delay_hours": 12,
    },
    {
        "nuts_id": "RO224",
        "name": "Galați",
        "lat": 45.43,
        "lon": 28.05,
        "distance_km": 170,
        "delay_hours": 18,
    },
    {
        "nuts_id": "RO211",
        "name": "Bacău",
        "lat": 46.57,
        "lon": 26.92,
        "distance_km": 210,
        "delay_hours": 24,
    },
]

# Total simulation duration in hours
TOTAL_HOURS = 48
# Number of time steps
NUM_STEPS = 24


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


def _risk_at_time(
    base_risk: float,
    distance_km: float,
    delay_hours: float,
    current_hour: float,
    rainfall_mm: float,
) -> float:
    """Calculate risk at a given time for a downstream region.

    Uses a sigmoid activation (flood wave arrives gradually) with
    exponential decay based on distance from the source.
    """
    if current_hour < delay_hours * 0.5:
        # Wave hasn't reached yet
        return max(0, base_risk * 0.05)

    # Sigmoid activation: smooth transition from 0 to 1 as wave arrives
    time_since_arrival = current_hour - delay_hours * 0.7
    activation = 1 / (1 + math.exp(-0.5 * time_since_arrival))

    # Distance decay
    decay = math.exp(-0.003 * distance_km)

    # Rainfall amplifier
    rain_factor = 1.0 + (rainfall_mm / 200.0) * 0.5

    risk = base_risk * activation * decay * rain_factor
    return min(100.0, max(0.0, risk))


def _alert_level(risk: float) -> str:
    if risk >= 75:
        return "emergency"
    if risk >= 60:
        return "critical"
    if risk >= 30:
        return "warning"
    return "info"


def _step_description(risk: float, name: str, hour: float) -> str:
    if risk >= 75:
        return f"URGENȚĂ: Undă de viitură ajunge la {name} la T+{hour:.0f}h"
    if risk >= 60:
        return f"RISC CRITIC: Nivel ridicat al apei la {name}"
    if risk >= 30:
        return f"AVERTIZARE: Creștere treptată a riscului la {name}"
    return f"Monitorizare: {name} — situație stabilă"


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
):
    """Generate a complete simulation timeline for the frontend time-slider.

    Returns `NUM_STEPS` time frames spanning `TOTAL_HOURS`.
    Each frame contains the risk state of all regions in the demo corridor.

    The frontend plays through these frames to animate the flood wave
    propagating downstream — demonstrating the GNN flow model from Task 5.
    """
    # Base risk from rainfall (same heuristic as ML demo)
    base_risk = min(100.0, 20.0 + rainfall_mm * 0.40)

    # Seasonal boost (spring/autumn = higher risk)
    seasonal_boost = 1.0
    if month in (3, 4, 5, 10, 11):
        seasonal_boost = 1.2
    elif month in (6, 7, 8):
        seasonal_boost = 1.1

    base_risk = min(100.0, base_risk * seasonal_boost)

    steps: list[TimeStep] = []
    hours_per_step = TOTAL_HOURS / NUM_STEPS

    for i in range(NUM_STEPS + 1):
        current_hour = i * hours_per_step
        regions: list[RegionState] = []

        for node in DEMO_CORRIDOR:
            risk = _risk_at_time(
                base_risk,
                node["distance_km"],
                node["delay_hours"],
                current_hour,
                rainfall_mm,
            )

            # Origin gets full rainfall
            node_rainfall = (
                rainfall_mm if node["distance_km"] == 0
                else rainfall_mm * math.exp(-0.005 * node["distance_km"])
            )

            level = _alert_level(risk)
            wave_active = risk > 15 and current_hour >= node["delay_hours"] * 0.5

            regions.append(
                RegionState(
                    nuts_id=node["nuts_id"],
                    name=node["name"],
                    lat=node["lat"],
                    lon=node["lon"],
                    risk_score=round(risk, 1),
                    alert_level=level,
                    wave_active=wave_active,
                    rainfall_mm=round(node_rainfall, 1),
                    description=_step_description(risk, node["name"], current_hour),
                )
            )

        label = f"T+{current_hour:.0f}h"
        if current_hour == 0:
            label = "T=0 (Start)"
        elif current_hour >= TOTAL_HOURS:
            label = f"T+{TOTAL_HOURS}h (End)"

        steps.append(
            TimeStep(
                step=i,
                hour=current_hour,
                label=label,
                regions=regions,
            )
        )

    return SimulationTimeline(
        scenario="Tecuci → Focșani → Buzău → Galați → Bacău",
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
