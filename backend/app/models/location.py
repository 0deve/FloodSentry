"""Location model — NUTS administrative regions (EU Standard)."""

from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.orm import relationship

from app.database import Base


class Location(Base):
    """Represents an EU NUTS administrative region.

    NUTS (Nomenclature of Territorial Units for Statistics) is the
    Eurostat geocode standard for referencing EU administrative divisions.
    Levels: 0 = Country, 1 = Major region, 2 = Region, 3 = County/Județ.
    """

    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    nuts_id = Column(String(10), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    level = Column(Integer, nullable=False, default=3)  # NUTS level: 2 or 3
    population = Column(Integer, nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)

    # Relationships
    infrastructure = relationship(
        "CriticalInfrastructure",
        back_populates="location",
        cascade="all, delete-orphan",
    )
    predictions = relationship(
        "FloodPrediction",
        back_populates="location",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Location(nuts_id='{self.nuts_id}', name='{self.name}')>"
