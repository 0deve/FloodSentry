"""CRUD router for NUTS Locations."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.location import Location
from app.models.infrastructure import CriticalInfrastructure
from app.schemas.location import (
    LocationCreate,
    LocationResponse,
    LocationUpdate,
    LocationWithInfrastructure,
)
from app.schemas.infrastructure import InfrastructureResponse

router = APIRouter(prefix="/api/v1/locations", tags=["Locations"])


@router.get("/", response_model=list[LocationResponse])
def list_locations(
    level: int | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """List all NUTS locations, optionally filtered by NUTS level."""
    query = db.query(Location)
    if level is not None:
        query = query.filter(Location.level == level)
    return query.offset(skip).limit(limit).all()


@router.get("/{nuts_id}", response_model=LocationResponse)
def get_location(nuts_id: str, db: Session = Depends(get_db)):
    """Get a single location by its NUTS ID."""
    location = db.query(Location).filter(Location.nuts_id == nuts_id).first()
    if not location:
        raise HTTPException(status_code=404, detail=f"Location '{nuts_id}' not found")
    return location


@router.post("/", response_model=LocationResponse, status_code=201)
def create_location(data: LocationCreate, db: Session = Depends(get_db)):
    """Create a new NUTS location."""
    existing = db.query(Location).filter(Location.nuts_id == data.nuts_id).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Location '{data.nuts_id}' already exists",
        )
    location = Location(**data.model_dump())
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


@router.patch("/{nuts_id}", response_model=LocationResponse)
def update_location(
    nuts_id: str, data: LocationUpdate, db: Session = Depends(get_db)
):
    """Partially update a location."""
    location = db.query(Location).filter(Location.nuts_id == nuts_id).first()
    if not location:
        raise HTTPException(status_code=404, detail=f"Location '{nuts_id}' not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(location, field, value)
    db.commit()
    db.refresh(location)
    return location


@router.delete("/{nuts_id}", status_code=204)
def delete_location(nuts_id: str, db: Session = Depends(get_db)):
    """Delete a location and all related data."""
    location = db.query(Location).filter(Location.nuts_id == nuts_id).first()
    if not location:
        raise HTTPException(status_code=404, detail=f"Location '{nuts_id}' not found")
    db.delete(location)
    db.commit()


# --- Task 2 special endpoint ---

@router.get(
    "/{nuts_id}/infrastructure",
    response_model=list[InfrastructureResponse],
)
def get_location_infrastructure(
    nuts_id: str,
    type: str | None = None,
    db: Session = Depends(get_db),
):
    """Get critical infrastructure within a NUTS region.

    Returns hospitals, schools, power stations, etc. for the given region.
    Optionally filter by infrastructure type.
    """
    # Verify location exists
    location = db.query(Location).filter(Location.nuts_id == nuts_id).first()
    if not location:
        raise HTTPException(status_code=404, detail=f"Location '{nuts_id}' not found")

    query = db.query(CriticalInfrastructure).filter(
        CriticalInfrastructure.nuts_id == nuts_id
    )
    if type:
        query = query.filter(CriticalInfrastructure.type == type)
    return query.all()
