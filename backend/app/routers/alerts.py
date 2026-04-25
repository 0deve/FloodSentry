"""Alerts router — CRUD + Alert Engine + CAP XML Export.

Task 7 additions:
- POST /evaluate  — Run the Alert Engine to auto-generate alerts
- GET  /{id}/export/cap — Download CAP XML for a specific alert
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.alert import Alert
from app.schemas.alert import AlertCreate, AlertResponse
from app.services.alert_engine import evaluate_and_create_alerts
from app.services.cap_xml import generate_cap_xml

router = APIRouter(prefix="/api/v1/alerts", tags=["Alerts"])


@router.get("/", response_model=list[AlertResponse])
def list_alerts(
    nuts_id: str | None = None,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """List alerts, optionally filtered by region and active status."""
    query = db.query(Alert)
    if nuts_id:
        query = query.filter(Alert.nuts_id == nuts_id)
    if active_only:
        query = query.filter(Alert.is_active == True)
    return query.order_by(Alert.created_at.desc()).offset(skip).limit(limit).all()


@router.post("/", response_model=AlertResponse, status_code=201)
def create_alert(data: AlertCreate, db: Session = Depends(get_db)):
    """Create a new alert."""
    alert = Alert(**data.model_dump())
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


@router.patch("/{alert_id}/resolve", response_model=AlertResponse)
def resolve_alert(alert_id: int, db: Session = Depends(get_db)):
    """Mark an alert as resolved."""
    alert = db.query(Alert).get(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.is_active = False
    alert.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)
    return alert


# ── Task 7: Alert Engine ────────────────────────────────────────


@router.post("/evaluate", response_model=list[AlertResponse])
def evaluate_alerts(db: Session = Depends(get_db)):
    """Run the Alert Engine to evaluate all predictions and generate alerts.

    The engine:
    - Fetches all predictions above WARNING threshold
    - Evaluates risk + population impact + infrastructure exposure
    - Escalates to EMERGENCY when risk > 75 AND affected > 5000 people
    - Creates new alerts (skips regions with existing active alerts)

    Returns the list of newly generated alerts.
    """
    new_alerts = evaluate_and_create_alerts(db)
    return new_alerts


# ── Task 7: CAP XML Export ──────────────────────────────────────


@router.get("/{alert_id}/export/cap")
def export_cap_xml(alert_id: int, db: Session = Depends(get_db)):
    """Export an alert as a CAP 1.2 XML document.

    The Common Alerting Protocol (CAP) is the global standard used by
    RO-Alert (Cell Broadcast) and similar government warning systems.

    Returns an XML file download with proper Content-Disposition header.
    """
    alert = db.query(Alert).get(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    xml_content = generate_cap_xml(alert)

    filename = f"FloodSentry_CAP_{alert.nuts_id}_{alert_id}.xml"
    return Response(
        content=xml_content,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
