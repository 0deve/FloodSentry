"""CRUD router for FloodPredictions."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.location import Location
from app.models.prediction import FloodPrediction
from app.schemas.prediction import PredictionCreate, PredictionResponse

router = APIRouter(prefix="/api/v1/predictions", tags=["Predictions"])


@router.get("/", response_model=list[PredictionResponse])
def list_predictions(
    nuts_id: str | None = None,
    hazard_type: str | None = None,
    min_risk: float = Query(default=0, ge=0, le=100),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """List predictions, optionally filtered by region, hazard type, or minimum risk."""
    query = db.query(FloodPrediction)
    if nuts_id:
        query = query.filter(FloodPrediction.nuts_id == nuts_id)
    if hazard_type:
        query = query.filter(FloodPrediction.hazard_type == hazard_type)
    if min_risk > 0:
        query = query.filter(FloodPrediction.risk_score >= min_risk)
    return (
        query.order_by(FloodPrediction.risk_score.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/{prediction_id}", response_model=PredictionResponse)
def get_prediction(prediction_id: int, db: Session = Depends(get_db)):
    """Get a single prediction by ID."""
    prediction = db.query(FloodPrediction).get(prediction_id)
    if not prediction:
        raise HTTPException(status_code=404, detail="Prediction not found")
    return prediction


@router.post("/", response_model=PredictionResponse, status_code=201)
def create_prediction(data: PredictionCreate, db: Session = Depends(get_db)):
    """Create a new flood prediction for a NUTS region."""
    # Verify location exists
    location = (
        db.query(Location).filter(Location.nuts_id == data.nuts_id).first()
    )
    if not location:
        raise HTTPException(
            status_code=404,
            detail=f"Location '{data.nuts_id}' not found",
        )
    prediction = FloodPrediction(**data.model_dump())
    db.add(prediction)
    db.commit()
    db.refresh(prediction)
    return prediction
