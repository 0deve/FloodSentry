"""Seed script — populates the FloodSentry database with real NUTS regions,
critical infrastructure, and ML-generated flood predictions.

Run from the backend/ directory:
    python scripts/seed_db.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone

from app.database import Base, engine, SessionLocal
from app.models.location import Location
from app.models.infrastructure import CriticalInfrastructure
from app.models.prediction import FloodPrediction
from app.ml.flood_classifier import FloodClassifier, FloodFeatures

# ── 1. NUTS-3 Regions (Romania + neighbours) ─────────────────────────────────

NUTS_REGIONS = [
    # --- Romania NUTS-3 counties ---
    {"nuts_id": "RO224", "name": "Galați",         "level": 3, "population": 250000,  "latitude": 45.44, "longitude": 28.03},
    {"nuts_id": "RO225", "name": "Tulcea",         "level": 3, "population": 213000,  "latitude": 45.18, "longitude": 28.80},
    {"nuts_id": "RO221", "name": "Brăila",         "level": 3, "population": 210000,  "latitude": 45.27, "longitude": 27.96},
    {"nuts_id": "RO223", "name": "Constanța",      "level": 3, "population": 684000,  "latitude": 44.17, "longitude": 28.63},
    {"nuts_id": "RO213", "name": "Iași",           "level": 3, "population": 855000,  "latitude": 47.15, "longitude": 27.59},
    {"nuts_id": "RO211", "name": "Bacău",          "level": 3, "population": 616000,  "latitude": 46.56, "longitude": 26.92},
    {"nuts_id": "RO216", "name": "Vaslui",         "level": 3, "population": 395000,  "latitude": 46.63, "longitude": 27.73},
    {"nuts_id": "RO214", "name": "Neamț",          "level": 3, "population": 470000,  "latitude": 46.97, "longitude": 26.38},
    {"nuts_id": "RO121", "name": "Brașov",         "level": 3, "population": 596000,  "latitude": 45.65, "longitude": 25.61},
    {"nuts_id": "RO122", "name": "Covasna",        "level": 3, "population": 210000,  "latitude": 45.85, "longitude": 26.18},
    {"nuts_id": "RO424", "name": "Timiș",          "level": 3, "population": 697000,  "latitude": 45.74, "longitude": 21.23},
    {"nuts_id": "RO312", "name": "Dâmbovița",      "level": 3, "population": 518000,  "latitude": 44.92, "longitude": 25.45},
    {"nuts_id": "RO315", "name": "Prahova",        "level": 3, "population": 762000,  "latitude": 45.03, "longitude": 26.02},
    {"nuts_id": "RO321", "name": "București",      "level": 3, "population": 2100000, "latitude": 44.43, "longitude": 26.10},
    {"nuts_id": "RO311", "name": "Argeș",          "level": 3, "population": 612000,  "latitude": 44.85, "longitude": 24.87},
    {"nuts_id": "RO414", "name": "Mehedinți",      "level": 3, "population": 265000,  "latitude": 44.63, "longitude": 22.65},
    {"nuts_id": "RO411", "name": "Dolj",           "level": 3, "population": 662000,  "latitude": 44.32, "longitude": 23.80},
    {"nuts_id": "RO421", "name": "Arad",           "level": 3, "population": 430000,  "latitude": 46.17, "longitude": 21.32},
    {"nuts_id": "RO422", "name": "Caraș-Severin",  "level": 3, "population": 295000,  "latitude": 45.30, "longitude": 22.07},
    {"nuts_id": "RO423", "name": "Hunedoara",      "level": 3, "population": 419000,  "latitude": 45.72, "longitude": 22.91},
    {"nuts_id": "RO112", "name": "Cluj",           "level": 3, "population": 729000,  "latitude": 46.77, "longitude": 23.60},
    {"nuts_id": "RO113", "name": "Mureș",          "level": 3, "population": 550000,  "latitude": 46.54, "longitude": 24.56},
    {"nuts_id": "RO212", "name": "Botoșani",       "level": 3, "population": 412000,  "latitude": 47.74, "longitude": 26.67},
    {"nuts_id": "RO215", "name": "Suceava",        "level": 3, "population": 688000,  "latitude": 47.65, "longitude": 26.25},
    {"nuts_id": "RO222", "name": "Buzău",          "level": 3, "population": 453000,  "latitude": 45.15, "longitude": 26.82},
]

# ── 2. Feature vectors for ML predictions ────────────────────────────────────
# Each entry: nuts_id → (soil_moisture, ndwi, snow_cover, rainfall_24h, temp_trend, elevation, slope, upstream_risk)

REGION_FEATURES = {
    "RO224": (0.85, 0.42,  0.00,  95.0,  2.5, 10.0,  0.8, 80.0),   # Galati - HIGH RISK fluvial
    "RO225": (0.78, 0.35,  0.00,  55.0,  1.8, 5.0,   0.5, 70.0),   # Tulcea - HIGH fluvial
    "RO221": (0.80, 0.38,  0.00,  70.0,  2.1, 12.0,  0.7, 75.0),   # Braila - HIGH fluvial
    "RO213": (0.75, 0.18,  0.00, 110.0,  1.5, 45.0,  2.1, 35.0),   # Iasi - pluvial
    "RO211": (0.70, 0.15,  0.00, 125.0,  1.2, 80.0,  3.5, 20.0),   # Bacau - pluvial
    "RO216": (0.82, 0.22,  0.00, 145.0,  1.0, 60.0,  2.8, 15.0),   # Vaslui - pluvial HIGH
    "RO223": (0.45, 0.08,  0.00,  12.0,  0.5, 8.0,   0.3,  5.0),   # Constanta - LOW
    "RO121": (0.55, 0.10,  0.60,  20.0, 12.0, 650.0, 8.5, 10.0),   # Brasov - snowmelt HIGH
    "RO122": (0.50, 0.08,  0.65,  15.0, 13.0, 700.0, 9.2, 12.0),   # Covasna - snowmelt HIGH
    "RO424": (0.65, 0.20,  0.00,  65.0,  1.5, 90.0,  2.0, 25.0),   # Timis - warning
    "RO312": (0.40, 0.05,  0.00,  10.0,  0.2, 180.0, 4.0,  3.0),   # Dambovita - LOW
    "RO315": (0.38, 0.03,  0.00,   8.0,  0.1, 220.0, 5.0,  2.0),   # Prahova - LOW
    "RO321": (0.42, 0.06,  0.00,  18.0,  0.8, 70.0,  1.0,  8.0),   # Bucuresti - LOW
    "RO311": (0.35, 0.02,  0.00,   5.0, -0.5, 380.0, 6.0,  1.0),   # Arges - LOW
    "RO414": (0.60, 0.15,  0.00,  45.0,  1.2, 120.0, 3.5, 30.0),   # Mehedinti - warning
    "RO411": (0.55, 0.12,  0.00,  30.0,  0.8, 90.0,  2.0, 20.0),   # Dolj - info
    "RO421": (0.48, 0.09,  0.00,  25.0,  0.6, 110.0, 2.5, 10.0),   # Arad - LOW
    "RO422": (0.52, 0.11,  0.30,  35.0,  4.0, 450.0, 7.0,  8.0),   # Caras-Severin - warning
    "RO423": (0.50, 0.10,  0.25,  28.0,  3.5, 400.0, 6.5,  5.0),   # Hunedoara - LOW
    "RO112": (0.42, 0.07,  0.10,  15.0,  1.0, 350.0, 4.5,  3.0),   # Cluj - LOW
    "RO113": (0.44, 0.08,  0.12,  18.0,  1.2, 320.0, 4.2,  4.0),   # Mures - LOW
    "RO212": (0.62, 0.16,  0.00,  55.0,  0.9, 150.0, 2.8, 15.0),   # Botosani - warning
    "RO215": (0.58, 0.13,  0.05,  45.0,  0.7, 280.0, 3.8, 10.0),   # Suceava - LOW
    "RO222": (0.65, 0.18,  0.00,  60.0,  1.3, 100.0, 2.5, 22.0),   # Buzau - warning
    "RO214": (0.60, 0.14,  0.08,  50.0,  1.1, 200.0, 5.0, 12.0),   # Neamt - warning
}

# ── 3. Infrastructure ─────────────────────────────────────────────────────────

INFRASTRUCTURE = [
    # Galati (very at risk)
    {"nuts_id": "RO224", "type": "hospital",   "name": "Spitalul Județean Galați",       "latitude": 45.44, "longitude": 28.03},
    {"nuts_id": "RO224", "type": "hospital",   "name": "Spitalul Municipal Galați",      "latitude": 45.46, "longitude": 28.05},
    {"nuts_id": "RO224", "type": "school",     "name": "Școala Nr. 11 Galați",           "latitude": 45.43, "longitude": 28.02},
    {"nuts_id": "RO224", "type": "school",     "name": "Colegiul Vasile Alecsandri",     "latitude": 45.44, "longitude": 28.04},
    {"nuts_id": "RO224", "type": "powerplant", "name": "Stație Electrică Galați Sud",   "latitude": 45.42, "longitude": 28.01},
    # Tulcea
    {"nuts_id": "RO225", "type": "hospital",   "name": "Spitalul Județean Tulcea",       "latitude": 45.18, "longitude": 28.80},
    {"nuts_id": "RO225", "type": "school",     "name": "Colegiul Delta Dunării",         "latitude": 45.19, "longitude": 28.81},
    # Braila
    {"nuts_id": "RO221", "type": "hospital",   "name": "Spitalul Județean Brăila",       "latitude": 45.27, "longitude": 27.96},
    {"nuts_id": "RO221", "type": "school",     "name": "Liceul Tehnic Brăila",           "latitude": 45.28, "longitude": 27.97},
    # Iasi
    {"nuts_id": "RO213", "type": "hospital",   "name": "Spitalul Sf. Spiridon Iași",    "latitude": 47.15, "longitude": 27.59},
    {"nuts_id": "RO213", "type": "hospital",   "name": "Spitalul Militar Iași",         "latitude": 47.16, "longitude": 27.60},
    {"nuts_id": "RO213", "type": "school",     "name": "Colegiul Național Iași",        "latitude": 47.14, "longitude": 27.58},
    # Bacau
    {"nuts_id": "RO211", "type": "hospital",   "name": "Spitalul Județean Bacău",       "latitude": 46.56, "longitude": 26.92},
    {"nuts_id": "RO211", "type": "school",     "name": "Colegiul Ferdinand Bacău",      "latitude": 46.57, "longitude": 26.93},
    # Vaslui
    {"nuts_id": "RO216", "type": "hospital",   "name": "Spitalul Județean Vaslui",      "latitude": 46.63, "longitude": 27.73},
    {"nuts_id": "RO216", "type": "school",     "name": "Colegiul Mihail Kogălniceanu",  "latitude": 46.64, "longitude": 27.74},
    # Brasov (snowmelt risk)
    {"nuts_id": "RO121", "type": "hospital",   "name": "Spitalul Clinic Brașov",        "latitude": 45.65, "longitude": 25.61},
    {"nuts_id": "RO121", "type": "school",     "name": "Colegiul Național Andrei Șaguna","latitude": 45.66, "longitude": 25.62},
    # Timis
    {"nuts_id": "RO424", "type": "hospital",   "name": "Spitalul Județean Timișoara",   "latitude": 45.74, "longitude": 21.23},
    {"nuts_id": "RO424", "type": "school",     "name": "Colegiul Național Banatean",    "latitude": 45.75, "longitude": 21.24},
    # Bucuresti
    {"nuts_id": "RO321", "type": "hospital",   "name": "Spitalul Colentina",            "latitude": 44.47, "longitude": 26.13},
    {"nuts_id": "RO321", "type": "hospital",   "name": "Spitalul Floreasca",            "latitude": 44.46, "longitude": 26.09},
    {"nuts_id": "RO321", "type": "school",     "name": "Colegiul Național Gh. Lazăr",   "latitude": 44.43, "longitude": 26.09},
]


def seed():
    print("🌱 FloodSentry DB Seed — Starting...")

    # Create all tables
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # ── Clear existing data ──────────────────────────────────────────────
        existing = db.query(Location).count()
        if existing > 0:
            print(f"   ℹ️  Database already has {existing} locations. Clearing and re-seeding...")
            db.query(FloodPrediction).delete()
            db.query(CriticalInfrastructure).delete()
            db.query(Location).delete()
            db.commit()

        # ── Seed Locations ───────────────────────────────────────────────────
        print(f"   📍 Seeding {len(NUTS_REGIONS)} NUTS regions...")
        for r in NUTS_REGIONS:
            db.add(Location(**r))
        db.commit()
        print(f"   ✅ Locations saved.")

        # ── Seed Infrastructure ──────────────────────────────────────────────
        print(f"   🏥 Seeding {len(INFRASTRUCTURE)} infrastructure items...")
        for i in INFRASTRUCTURE:
            db.add(CriticalInfrastructure(**i))
        db.commit()
        print(f"   ✅ Infrastructure saved.")

        # ── Seed Predictions via ML ──────────────────────────────────────────
        print(f"   🤖 Running XGBoost model for all regions...")
        clf = FloodClassifier()
        import calendar
        current_month = datetime.now(timezone.utc).month

        predictions_created = 0
        for region in NUTS_REGIONS:
            nuts_id = region["nuts_id"]
            feats = REGION_FEATURES.get(nuts_id)
            if not feats:
                continue
            soil_moisture, ndwi, snow_cover, rainfall_24h, temp_trend, elevation, slope, upstream_risk = feats

            features = FloodFeatures(
                nuts_id=nuts_id,
                month=current_month,
                soil_moisture=soil_moisture,
                ndwi=ndwi,
                snow_cover=snow_cover,
                rainfall_24h=rainfall_24h,
                temp_trend=temp_trend,
                elevation=elevation,
                slope=slope,
                upstream_risk=upstream_risk,
            )
            result = clf.predict(features)

            pred = FloodPrediction(
                nuts_id=nuts_id,
                risk_score=result.risk_score,
                hazard_type=result.hazard_type,
                affected_population=int(region["population"] * result.flood_probability),
                rainfall_mm=rainfall_24h,
                soil_moisture=soil_moisture,
                ndwi=ndwi,
                snow_water_equivalent=snow_cover,
                river_discharge=upstream_risk,
                temperature_c=temp_trend,
                model_version=result.model_version,
                predicted_at=datetime.now(timezone.utc),
            )
            db.add(pred)
            predictions_created += 1

        db.commit()
        print(f"   ✅ {predictions_created} predictions saved.")

        # ── Summary ──────────────────────────────────────────────────────────
        total_locs = db.query(Location).count()
        total_preds = db.query(FloodPrediction).count()
        high_risk = db.query(FloodPrediction).filter(FloodPrediction.risk_score >= 60).count()
        print(f"\n🎉 Seed complete!")
        print(f"   Locations:   {total_locs}")
        print(f"   Predictions: {total_preds}")
        print(f"   High risk:   {high_risk} regions (score >= 60)")
        print(f"\n   🚀 Start the server and open http://localhost:5173")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
