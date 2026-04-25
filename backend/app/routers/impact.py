"""Impact Analysis router — Impact-Based Forecasting (Task 2 core endpoint)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.location import Location
from app.models.infrastructure import CriticalInfrastructure
from app.models.prediction import FloodPrediction
import random
import hashlib
from app.schemas.impact import (
    ImpactSummaryResponse,
    RegionImpact,
    InfrastructureAtRisk,
)

router = APIRouter(prefix="/api/v1/impact", tags=["Impact Analysis"])


def _risk_to_alert_level(risk_score: float) -> str:
    """Convert a numeric risk score to a human-readable alert level."""
    if risk_score >= 85:
        return "emergency"
    elif risk_score >= 60:
        return "critical"
    elif risk_score >= 30:
        return "warning"
    return "info"


def _build_summary_text(
    nuts_id: str,
    region_name: str,
    alert_level: str,
    infra_items: list[InfrastructureAtRisk],
) -> str:
    """Build a human-readable impact summary string."""
    level_ro = {
        "emergency": "Urgență Maximă",
        "critical": "Risc Critic",
        "warning": "Avertizare",
        "info": "Informare",
    }
    parts = [f"{level_ro.get(alert_level, alert_level)} în {nuts_id} ({region_name})."]

    if infra_items:
        asset_parts = []
        for item in infra_items:
            if item.count == 1:
                asset_parts.append(item.names[0] if item.names else item.type)
            else:
                asset_parts.append(f"{item.count} {item.type}s")
        parts.append("Infrastructură la risc: " + ", ".join(asset_parts) + ".")

    return " ".join(parts)


from datetime import datetime, timedelta, timezone

@router.get("/summary", response_model=ImpactSummaryResponse)
def get_impact_summary(
    min_risk: float = Query(default=30.0, ge=0, le=100),
    days_ahead: int = Query(default=0, ge=0, le=7),
    simulate_storm: bool = Query(default=False, description="Simulate massive storm over Romania for demo"),
    db: Session = Depends(get_db),
):
    """Return an aggregated impact summary across all NUTS regions.

    Reports not just risk percentages but concrete infrastructure impacts:
    - How many hospitals / schools are at risk
    - Estimated affected population
    - Human-readable summary per region

    This is the core of the Impact-Based Forecasting feature.
    """
    
    target_date = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    
    # Get the latest predictions
    query = db.query(FloodPrediction)
    
    if not simulate_storm:
        query = query.filter(FloodPrediction.risk_score >= min_risk)
    
    # Filter by the requested forecast day (sqlite compatible approach for dates)
    query = query.filter(func.date(FloodPrediction.predicted_at) == target_date.date())
    
    predictions = query.order_by(FloodPrediction.risk_score.desc()).all()

    # Deduplicate: keep highest risk per nuts_id
    seen: dict[str, FloodPrediction] = {}
    for pred in predictions:
        if pred.nuts_id not in seen or pred.risk_score > seen[pred.nuts_id].risk_score:
            seen[pred.nuts_id] = pred

    total_affected_pop = 0
    total_hospitals = 0
    total_schools = 0
    regions: list[RegionImpact] = []

    for nuts_id, pred in seen.items():
        # Fetch location info first so we can use its coordinates
        location = db.query(Location).filter(Location.nuts_id == nuts_id).first()
        region_name = location.name if location else nuts_id

        # Apply storm simulation overlay (Scattered Europe-wide)
        if simulate_storm and location:
            # Deterministic vulnerability factor per NUTS ID (0.0 to 1.0)
            h = int(hashlib.md5(nuts_id.encode('utf-8')).hexdigest(), 16)
            vuln_factor = (h % 100) / 100.0
            
            # Base potential is scattered globally across all Europe
            max_potential = 5.0 + (vuln_factor * 25.0)
            
            # The storm builds up over the 7 days (days_ahead)
            intensity = max_potential + (days_ahead * 10.0) * vuln_factor
            
            # Add scattered noise
            storm_risk = intensity * (0.8 + vuln_factor * 0.5)
            
            if storm_risk > 15:
                pred.risk_score = min(98.5, max(pred.risk_score, storm_risk))
                # Flash floods early on, river floods later
                pred.hazard_type = "pluvial" if days_ahead < 3 else "fluvial"
                
                # Dynamic population calculation (much smaller % affected, highly realistic)
                base_pop = 100000 + (h % 700000)
                # Only ~1-3% of people are actually affected by floods even at 100% risk
                pred.affected_population = int(base_pop * (pred.risk_score / 100.0) * 0.025)
                
            # Keep baseline weather non-zero visually for the rest of Europe
            elif pred.risk_score < 5.0:
                pred.risk_score = 5.0 + random.uniform(0.1, 4.0)
            
        if pred.risk_score < min_risk:
            continue

        # Fetch infrastructure at risk in this region
        infra_rows = (
            db.query(CriticalInfrastructure)
            .filter(CriticalInfrastructure.nuts_id == nuts_id)
            .all()
        )

        # Group by type
        by_type: dict[str, list[str]] = {}
        for row in infra_rows:
            by_type.setdefault(row.type, []).append(row.name)

        infra_summary = [
            InfrastructureAtRisk(type=t, count=len(names), names=names)
            for t, names in by_type.items()
        ]

        alert_level = _risk_to_alert_level(pred.risk_score)
        summary_text = _build_summary_text(
            nuts_id, region_name, alert_level, infra_summary
        )

        affected_pop = pred.affected_population or 0
        total_affected_pop += affected_pop
        total_hospitals += by_type.get("hospital", []).__len__()
        total_schools += by_type.get("school", []).__len__()

        regions.append(
            RegionImpact(
                nuts_id=nuts_id,
                region_name=region_name,
                risk_score=pred.risk_score,
                hazard_type=pred.hazard_type,
                affected_population=affected_pop,
                infrastructure_at_risk=infra_summary,
                alert_level=alert_level,
                summary_text=summary_text,
            )
        )

    # Sort regions by risk (highest first)
    regions.sort(key=lambda r: r.risk_score, reverse=True)

    return ImpactSummaryResponse(
        total_regions_at_risk=len(regions),
        total_affected_population=total_affected_pop,
        total_hospitals_at_risk=total_hospitals,
        total_schools_at_risk=total_schools,
        regions=regions,
    )
