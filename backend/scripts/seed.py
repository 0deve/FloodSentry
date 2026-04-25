"""Seed script — populate the database with real-world demo data.

Run from the backend directory:
    python -m scripts.seed
"""

import sys
import os

# Ensure the backend directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base, engine, SessionLocal
from app.models import Location, CriticalInfrastructure, FloodPrediction, Alert


def seed():
    """Insert seed data for the FloodSentry demo."""
    # Disable SQL echo for cleaner output
    engine.echo = False

    # Recreate tables
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # Clear existing data (idempotent re-runs)
        db.query(Alert).delete()
        db.query(FloodPrediction).delete()
        db.query(CriticalInfrastructure).delete()
        db.query(Location).delete()
        db.commit()

        # ─── LOCATIONS (NUTS-3 Regions) ──────────────────────────────
        locations = [
            Location(
                nuts_id="RO224",
                name="Județul Galați",
                level=3,
                population=490000,
                latitude=45.44,
                longitude=28.05,
            ),
            Location(
                nuts_id="RO225",
                name="Județul Vrancea",
                level=3,
                population=320000,
                latitude=45.70,
                longitude=27.19,
            ),
            Location(
                nuts_id="RO211",
                name="Județul Bacău",
                level=3,
                population=580000,
                latitude=46.57,
                longitude=26.91,
            ),
            Location(
                nuts_id="RO226",
                name="Județul Vaslui",
                level=3,
                population=380000,
                latitude=46.64,
                longitude=27.73,
            ),
            Location(
                nuts_id="HU333",
                name="Csongrád-Csanád",
                level=3,
                population=400000,
                latitude=46.26,
                longitude=20.15,
            ),
            Location(
                nuts_id="BG341",
                name="Burgas",
                level=3,
                population=410000,
                latitude=42.50,
                longitude=27.47,
            ),
        ]
        db.add_all(locations)
        db.flush()

        # ─── CRITICAL INFRASTRUCTURE ─────────────────────────────────
        infrastructure = [
            # Galați
            CriticalInfrastructure(
                nuts_id="RO224",
                type="hospital",
                name="Spitalul Județean de Urgență Sf. Apostol Andrei",
                latitude=45.4388,
                longitude=28.0458,
            ),
            CriticalInfrastructure(
                nuts_id="RO224",
                type="hospital",
                name="Spitalul de Pneumoftiziologie Galați",
                latitude=45.4412,
                longitude=28.0523,
            ),
            CriticalInfrastructure(
                nuts_id="RO224",
                type="school",
                name="Școala Gimnazială Nr. 12",
                latitude=45.4350,
                longitude=28.0400,
            ),
            CriticalInfrastructure(
                nuts_id="RO224",
                type="school",
                name="Liceul Teoretic Dunărea",
                latitude=45.4420,
                longitude=28.0380,
            ),
            CriticalInfrastructure(
                nuts_id="RO224",
                type="school",
                name="Colegiul Național Vasile Alecsandri",
                latitude=45.4395,
                longitude=28.0510,
            ),
            CriticalInfrastructure(
                nuts_id="RO224",
                type="power_station",
                name="Stația de Transformare Barboși",
                latitude=45.4600,
                longitude=28.0200,
            ),
            # Bacău
            CriticalInfrastructure(
                nuts_id="RO211",
                type="hospital",
                name="Spitalul Județean de Urgență Bacău",
                latitude=46.5670,
                longitude=26.9130,
            ),
            CriticalInfrastructure(
                nuts_id="RO211",
                type="school",
                name="Colegiul Național Ferdinand I Bacău",
                latitude=46.5680,
                longitude=26.9090,
            ),
            # Vrancea
            CriticalInfrastructure(
                nuts_id="RO225",
                type="hospital",
                name="Spitalul Județean de Urgență Focșani",
                latitude=45.6960,
                longitude=27.1850,
            ),
            # Hungary — Csongrád
            CriticalInfrastructure(
                nuts_id="HU333",
                type="hospital",
                name="Szegedi Tudományegyetem Szent-Györgyi Albert Klinikai Központ",
                latitude=46.2530,
                longitude=20.1480,
            ),
            CriticalInfrastructure(
                nuts_id="HU333",
                type="school",
                name="Szegedi Tudományegyetem",
                latitude=46.2545,
                longitude=20.1495,
            ),
        ]
        db.add_all(infrastructure)
        db.flush()

        # ─── FLOOD PREDICTIONS ───────────────────────────────────────
        predictions = [
            # Galați — high fluvial risk (Dunăre/Siret)
            FloodPrediction(
                nuts_id="RO224",
                risk_score=91.2,
                hazard_type="fluvial",
                affected_population=12000,
                rainfall_mm=85.3,
                soil_moisture=0.92,
                ndwi=0.65,
                river_discharge=3200.0,
                temperature_c=14.5,
                model_version="xgb-v0.1",
            ),
            # Bacău — moderate pluvial risk
            FloodPrediction(
                nuts_id="RO211",
                risk_score=67.5,
                hazard_type="pluvial",
                affected_population=4500,
                rainfall_mm=62.1,
                soil_moisture=0.78,
                ndwi=0.42,
                temperature_c=16.0,
                model_version="xgb-v0.1",
            ),
            # Vrancea — snowmelt risk
            FloodPrediction(
                nuts_id="RO225",
                risk_score=54.8,
                hazard_type="snowmelt",
                affected_population=2000,
                snow_water_equivalent=120.5,
                temperature_c=12.3,
                model_version="xgb-v0.1",
            ),
            # Vaslui — low risk
            FloodPrediction(
                nuts_id="RO226",
                risk_score=22.0,
                hazard_type="fluvial",
                affected_population=500,
                rainfall_mm=15.0,
                soil_moisture=0.35,
                river_discharge=450.0,
                temperature_c=15.0,
                model_version="xgb-v0.1",
            ),
            # Hungary — moderate fluvial
            FloodPrediction(
                nuts_id="HU333",
                risk_score=72.3,
                hazard_type="fluvial",
                affected_population=6000,
                rainfall_mm=55.0,
                soil_moisture=0.81,
                ndwi=0.55,
                river_discharge=2800.0,
                temperature_c=17.0,
                model_version="xgb-v0.1",
            ),
        ]
        db.add_all(predictions)
        db.flush()

        # ─── ALERTS ──────────────────────────────────────────────────
        alerts = [
            Alert(
                nuts_id="RO224",
                prediction_id=None,  # Will link after commit
                level="emergency",
                title="Risc Critic de Inundație — Galați (Dunăre/Siret)",
                description=(
                    "Risc Critic în RO224 (Galați). Nivel de risc: 91.2. "
                    "Infrastructură la risc: Spitalul Județean Sf. Apostol Andrei, "
                    "3 școli, Stația de Transformare Barboși. "
                    "Populație afectată estimată: 12.000."
                ),
                is_active=True,
            ),
            Alert(
                nuts_id="RO211",
                level="critical",
                title="Avertizare Pluvială — Bacău",
                description=(
                    "Risc ridicat de flash-flood în RO211 (Bacău). "
                    "Nivel de risc: 67.5. Precipitații intense prognozate."
                ),
                is_active=True,
            ),
            Alert(
                nuts_id="HU333",
                level="critical",
                title="Figyelmeztetés — Csongrád-Csanád (Tisza)",
                description=(
                    "Risc ridicat fluvial în HU333 (Csongrád-Csanád). "
                    "Debit crescut pe Tisza. Nivel de risc: 72.3."
                ),
                is_active=True,
            ),
        ]
        db.add_all(alerts)

        db.commit()
        print("[OK] Seed data inserted successfully!")
        print(f"   Locations: {len(locations)}")
        print(f"   Infrastructure: {len(infrastructure)}")
        print(f"   Predictions: {len(predictions)}")
        print(f"   Alerts: {len(alerts)}")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Error seeding data: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
