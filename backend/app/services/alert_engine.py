"""Alert Engine — Automated alert generation based on risk + impact analysis.

Evaluates:
- Flood probability (ML risk score)
- Population impact (affected_population)
- Critical infrastructure exposure

Severity escalation rules:
- EMERGENCY: risk >= 75 AND affected_population > 5000
- CRITICAL: risk >= 60
- WARNING: risk >= 30
- INFO: risk < 30
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.prediction import FloodPrediction
from app.models.location import Location
from app.models.infrastructure import CriticalInfrastructure

logger = logging.getLogger(__name__)


# ── Severity Thresholds ─────────────────────────────────────────
EMERGENCY_RISK_THRESHOLD = 75.0
EMERGENCY_POP_THRESHOLD = 5000
CRITICAL_THRESHOLD = 60.0
WARNING_THRESHOLD = 30.0


def _determine_severity(
    risk_score: float,
    affected_population: int,
    infra_count: int,
) -> str:
    """Determine alert severity from risk score + impact metrics.

    Follows the Task 7 specification:
    - Risk > 75 AND impact > 5000 people → EMERGENCY
    - Risk >= 60 → CRITICAL
    - Risk >= 30 → WARNING
    - Otherwise → INFO
    """
    if (
        risk_score >= EMERGENCY_RISK_THRESHOLD
        and affected_population > EMERGENCY_POP_THRESHOLD
    ):
        return "emergency"
    if risk_score >= CRITICAL_THRESHOLD:
        return "critical"
    if risk_score >= WARNING_THRESHOLD:
        return "warning"
    return "info"


def _build_alert_title(
    region_name: str,
    hazard_type: str,
    severity: str,
) -> str:
    """Build a human-readable alert title."""
    hazard_labels = {
        "fluvial": "Inundație fluvială",
        "pluvial": "Inundație pluvială (Flash Flood)",
        "snowmelt": "Inundație din topirea zăpezii",
    }
    severity_labels = {
        "emergency": "URGENȚĂ MAXIMĂ",
        "critical": "RISC CRITIC",
        "warning": "AVERTIZARE",
        "info": "INFORMARE",
    }
    hazard = hazard_labels.get(hazard_type, hazard_type)
    level = severity_labels.get(severity, severity.upper())
    return f"[{level}] {hazard} — {region_name}"


def _build_alert_description(
    nuts_id: str,
    region_name: str,
    risk_score: float,
    hazard_type: str,
    affected_population: int,
    infrastructure: list[CriticalInfrastructure],
) -> str:
    """Build a detailed alert description with impact analysis."""
    parts = []

    parts.append(
        f"Risc de inundație de tip {'fluvial (râuri)' if hazard_type == 'fluvial' else 'pluvial (ploi torențiale)' if hazard_type == 'pluvial' else 'topire zăpadă'} "
        f"în regiunea {region_name} ({nuts_id}). "
        f"Scor de risc: {risk_score:.1f}/100."
    )

    if affected_population > 0:
        parts.append(
            f"Populație estimată afectată: {affected_population:,} persoane."
        )

    if infrastructure:
        by_type: dict[str, list[str]] = {}
        for item in infrastructure:
            by_type.setdefault(item.type, []).append(item.name)

        infra_parts = []
        for itype, names in by_type.items():
            type_label = {
                "hospital": "spitale",
                "school": "școli",
                "power_station": "stații de transformare",
                "road": "drumuri principale",
            }.get(itype, itype)
            infra_parts.append(
                f"{len(names)} {type_label} ({', '.join(names[:3])}{'…' if len(names) > 3 else ''})"
            )
        parts.append(
            "Infrastructură critică la risc: " + "; ".join(infra_parts) + "."
        )

    if risk_score >= EMERGENCY_RISK_THRESHOLD:
        parts.append(
            "Se recomandă evacuarea imediată a zonelor din lunca inundabilă."
        )

    return " ".join(parts)


def evaluate_and_create_alerts(db: Session) -> list[Alert]:
    """Evaluate all current predictions and generate/update alerts.

    This is the core Alert Engine logic. It:
    1. Gets all active predictions
    2. For each prediction above WARNING threshold, generates an alert
    3. Applies severity escalation based on population + infrastructure
    4. Deduplicates — won't create duplicate alerts for the same region

    Returns the list of newly created alerts.
    """
    # Get all predictions, deduplicate by nuts_id (keep highest risk)
    predictions = (
        db.query(FloodPrediction)
        .filter(FloodPrediction.risk_score >= WARNING_THRESHOLD)
        .order_by(FloodPrediction.risk_score.desc())
        .all()
    )

    seen: dict[str, FloodPrediction] = {}
    for pred in predictions:
        if pred.nuts_id not in seen:
            seen[pred.nuts_id] = pred

    new_alerts: list[Alert] = []

    for nuts_id, pred in seen.items():
        # Check if there's already an active alert for this region
        existing = (
            db.query(Alert)
            .filter(Alert.nuts_id == nuts_id, Alert.is_active == True)
            .first()
        )
        if existing:
            continue

        # Fetch location info
        location = (
            db.query(Location).filter(Location.nuts_id == nuts_id).first()
        )
        region_name = location.name if location else nuts_id

        # Fetch infrastructure at risk
        infrastructure = (
            db.query(CriticalInfrastructure)
            .filter(CriticalInfrastructure.nuts_id == nuts_id)
            .all()
        )

        affected_pop = pred.affected_population or 0
        infra_count = len(infrastructure)

        severity = _determine_severity(
            pred.risk_score, affected_pop, infra_count
        )

        title = _build_alert_title(region_name, pred.hazard_type, severity)
        description = _build_alert_description(
            nuts_id,
            region_name,
            pred.risk_score,
            pred.hazard_type,
            affected_pop,
            infrastructure,
        )

        alert = Alert(
            nuts_id=nuts_id,
            prediction_id=pred.id,
            level=severity,
            title=title,
            description=description,
        )
        db.add(alert)
        new_alerts.append(alert)

    if new_alerts:
        db.commit()
        for a in new_alerts:
            db.refresh(a)
        logger.info(f"Alert Engine: generated {len(new_alerts)} new alerts.")

    return new_alerts
