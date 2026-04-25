"""FloodPrediction model — Multi-hazard risk assessment."""

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.database import Base


class FloodPrediction(Base):
    """Represents a flood risk prediction for a NUTS region.

    Supports three hazard types:
    - fluvial: River overflow (modeled via GNN / HydroSHEDS graph)
    - pluvial: Flash floods from torrential rain
    - snowmelt: Flooding from rapid snow melt
    """

    __tablename__ = "flood_predictions"

    id = Column(Integer, primary_key=True, index=True)
    nuts_id = Column(
        String(10),
        ForeignKey("locations.nuts_id"),
        nullable=False,
        index=True,
    )
    risk_score = Column(Float, nullable=False)  # 0-100
    hazard_type = Column(
        String(50), nullable=False, default="fluvial"
    )  # fluvial, pluvial, snowmelt
    affected_population = Column(Integer, nullable=True)

    # ML Feature columns — inputs to the prediction model
    rainfall_mm = Column(Float, nullable=True)
    soil_moisture = Column(Float, nullable=True)
    ndwi = Column(Float, nullable=True)  # Normalized Difference Water Index
    snow_water_equivalent = Column(Float, nullable=True)
    river_discharge = Column(Float, nullable=True)
    temperature_c = Column(Float, nullable=True)

    # Metadata
    predicted_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    model_version = Column(String(50), nullable=True, default="xgb-v0.1")

    # Relationship
    location = relationship("Location", back_populates="predictions")

    def __repr__(self) -> str:
        return (
            f"<FloodPrediction(nuts_id='{self.nuts_id}', "
            f"risk={self.risk_score}, type='{self.hazard_type}')>"
        )
