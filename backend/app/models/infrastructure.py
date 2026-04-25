"""CriticalInfrastructure model — OSM-sourced assets at risk."""

from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class CriticalInfrastructure(Base):
    """Represents critical infrastructure within a NUTS region.

    Data sourced from OpenStreetMap via Overpass API.
    Used in Impact-Based Forecasting to report not just risk scores,
    but concrete affected assets (hospitals, schools, etc.).
    """

    __tablename__ = "critical_infrastructure"

    id = Column(Integer, primary_key=True, index=True)
    nuts_id = Column(
        String(10),
        ForeignKey("locations.nuts_id"),
        nullable=False,
        index=True,
    )
    type = Column(String(50), nullable=False)  # hospital, school, power_station, road
    name = Column(String(200), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)

    # Relationship
    location = relationship("Location", back_populates="infrastructure")

    def __repr__(self) -> str:
        return f"<CriticalInfrastructure(type='{self.type}', name='{self.name}')>"
