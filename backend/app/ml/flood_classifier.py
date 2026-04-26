"""Flood Risk Classifier.

XGBoost-based multi-hazard flood probability classifier.

Features
-------------------------------------
Temporal:
  • month             : 1-12
  • is_winter         : 1 if month in {12, 1, 2, 3}

Satellite (Copernicus):
  • soil_moisture     : 0-1  (Sentinel-1 SAR proxy)
  • ndwi              : -1 to +1  (Sentinel-2 surface water)
  • ndvi              : 0-1  (vegetation cover — absorbs water)
  • snow_cover        : 0-1  (FSC / 100)

Meteorological (Open-Meteo ERA5):
  • rainfall_24h      : mm in the last 24 h
  • temp_trend        : ΔT °C over 48 h

Geographical:
  • elevation         : metres above sea level
  • slope             : terrain slope (°)

Graph (HydroNetwork):
  • upstream_risk     : propagated risk score from upstream NUTS (0-100)

Target:
  • is_flooded        : binary 0/1 (from Copernicus EMS ground truth)

Model
------
XGBClassifier — outputs probability P(flood) in [0, 1].
The final risk score returned to the API = P(flood) × 100.

Training data
--------------
In production: joined EMS ground-truth + Copernicus feature time-series.
For the hackathon MVP: a synthetic dataset that encodes hydrological
domain knowledge to produce realistic decision boundaries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.services.ems_ground_truth import EMSGroundTruthService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature schema (column order matters for XGBoost)
# ---------------------------------------------------------------------------

FEATURE_COLUMNS: list[str] = [
    "month",
    "is_winter",
    "soil_moisture",
    "ndwi",
    "ndvi",
    "snow_cover",
    "rainfall_24h",
    "temp_trend",
    "elevation",
    "slope",
    "upstream_risk",
]

# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------


@dataclass
class FloodFeatures:
    """Input feature vector for the flood classifier."""

    nuts_id: str

    # Temporal
    month: int = field(default_factory=lambda: datetime.now(timezone.utc).month)
    is_winter: int = 0          # derived from month

    # Satellite
    soil_moisture: float = 0.3  # 0-1
    ndwi: float = -0.2          # -1 to +1
    ndvi: float = 0.5           # 0-1  (typical vegetated area)
    snow_cover: float = 0.0     # 0-1 (FSC / 100)

    # Meteo
    rainfall_24h: float = 0.0   # mm
    temp_trend: float = 0.0     # ΔT °C / 48 h

    # Geography
    elevation: float = 150.0    # m (mean for NUTS region)
    slope: float = 2.0          # degrees

    # Graph feature
    upstream_risk: float = 0.0  # 0-100 (propagated from HydroNetwork)

    def __post_init__(self) -> None:
        self.is_winter = 1 if self.month in {12, 1, 2, 3} else 0

    def to_feature_vector(self) -> list[float]:
        """Return a list aligned with FEATURE_COLUMNS."""
        return [
            float(self.month),
            float(self.is_winter),
            self.soil_moisture,
            self.ndwi,
            self.ndvi,
            self.snow_cover,
            self.rainfall_24h,
            self.temp_trend,
            self.elevation,
            self.slope,
            self.upstream_risk,
        ]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("nuts_id", None)
        return d


@dataclass
class PredictionResult:
    """Output of the flood classifier for a single NUTS region."""

    nuts_id: str
    flood_probability: float        # 0-1
    risk_score: float               # 0-100 (= flood_probability × 100)
    hazard_type: str                # dominant hazard driver
    dominant_feature: str           # human-readable explanation
    features_used: dict[str, float]
    model_version: str = "xgb-v1.0"
    predicted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Synthetic training data generator
# ---------------------------------------------------------------------------

_RNG = np.random.default_rng(42)


def _generate_synthetic_training_data(n_samples: int = 2000) -> pd.DataFrame:
    """Generate a labelled dataset encoding hydrological domain knowledge.

    Rules encoded (derived from Copernicus EMS historical patterns):
    - High rainfall (>50 mm/24h) + high soil moisture → flood
    - High snowmelt (snow_cover > 0.4) + positive temp_trend → flood
    - NDWI > 0.2 (surface water already elevated) + any rain → flood
    - High upstream risk (>70) adds pressure regardless of local weather
    - Low elevation + high rainfall combination is critical
    - Summer/autumn events: pluvial dominant
    - Winter/spring snowmelt: snowmelt dominant
    """

    months = _RNG.integers(1, 13, size=n_samples)
    is_winter = np.isin(months, [12, 1, 2, 3]).astype(float)

    soil_moisture = _RNG.uniform(0.05, 0.95, n_samples)
    ndwi = _RNG.uniform(-0.8, 0.6, n_samples)
    ndvi = _RNG.uniform(0.0, 0.9, n_samples)
    snow_cover = np.where(is_winter, _RNG.uniform(0.0, 0.9, n_samples), _RNG.uniform(0.0, 0.15, n_samples))

    rainfall_24h = _RNG.exponential(scale=15.0, size=n_samples)  # most days low rain
    rainfall_24h = np.clip(rainfall_24h, 0, 200)
    temp_trend = _RNG.normal(0, 5, n_samples)

    elevation = _RNG.uniform(10, 800, n_samples)
    slope = _RNG.uniform(0.1, 15, n_samples)
    upstream_risk = _RNG.uniform(0, 100, n_samples)

    # ---- Label generation via domain rules ----
    flood_score = np.zeros(n_samples)

    # Rule 1: Heavy rainfall + saturated soil
    flood_score += np.where(rainfall_24h > 30, (rainfall_24h - 30) / 170.0 * 0.45, 0.0)
    flood_score += soil_moisture * 0.20

    # Rule 2: Snowmelt trigger
    snowmelt_trigger = (snow_cover > 0.35) & (temp_trend > 4.0)
    flood_score += np.where(snowmelt_trigger, 0.40, 0.0)
    flood_score += np.where(is_winter.astype(bool) & (snow_cover > 0.5), snow_cover * 0.15, 0.0)

    # Rule 3: Surface water already elevated (NDWI)
    flood_score += np.where(ndwi > 0.0, ndwi * 0.25, 0.0)

    # Rule 4: Upstream pressure
    flood_score += (upstream_risk / 100.0) * 0.25

    # Rule 5: Low elevation increases vulnerability
    elev_factor = np.clip(1.0 - elevation / 800.0, 0.0, 1.0)
    flood_score += elev_factor * 0.10

    # Add noise
    flood_score += _RNG.normal(0, 0.05, n_samples)
    flood_score = np.clip(flood_score, 0.0, 1.0)

    # Convert to binary label with 0.50 threshold
    is_flooded = (flood_score > 0.50).astype(int)

    df = pd.DataFrame(
        {
            "month": months,
            "is_winter": is_winter,
            "soil_moisture": soil_moisture,
            "ndwi": ndwi,
            "ndvi": ndvi,
            "snow_cover": snow_cover,
            "rainfall_24h": rainfall_24h,
            "temp_trend": temp_trend,
            "elevation": elevation,
            "slope": slope,
            "upstream_risk": upstream_risk,
            "is_flooded": is_flooded,
        }
    )
    logger.info(
        "Synthetic training set: %d samples, flood rate=%.1f%%",
        n_samples,
        is_flooded.mean() * 100,
    )
    return df


def _build_real_training_data() -> pd.DataFrame:
    """Build training dataset by combining real EMS events with synthetic background."""
    # 1. Start with a solid background of physical rules
    base_df = _generate_synthetic_training_data(n_samples=3000)
    
    # 2. Inject real Copernicus EMS Ground Truth
    ems = EMSGroundTruthService()
    samples = ems.get_labelled_samples()
    
    real_rows = []
    for s in samples:
        # Reconstruct environmental features matching the real hazard type
        # In a full pipeline, we would query Sentinel Hub for the exact date.
        month = s.event_start.month
        is_winter = 1 if month in [12, 1, 2, 3] else 0
        
        row = {
            "month": month,
            "is_winter": is_winter,
            "soil_moisture": 0.8 if s.hazard_type in ("pluvial", "fluvial") else 0.5,
            "ndwi": 0.4 if s.hazard_type == "fluvial" else 0.1,
            "ndvi": _RNG.uniform(0.3, 0.7),
            "snow_cover": 0.6 if s.hazard_type == "snowmelt" else 0.0,
            "rainfall_24h": _RNG.uniform(50, 150) if s.hazard_type == "pluvial" else _RNG.uniform(0, 10),
            "temp_trend": _RNG.uniform(5, 12) if s.hazard_type == "snowmelt" else 0.0,
            "elevation": _RNG.uniform(10, 300),
            "slope": _RNG.uniform(0.1, 5),
            "upstream_risk": _RNG.uniform(60, 100) if s.hazard_type == "fluvial" else 0.0,
            "is_flooded": s.is_flooded,
        }
        real_rows.append(row)
        
    if real_rows:
        real_df = pd.DataFrame(real_rows)
        # Duplicate the real samples to give them more weight in the MVP
        real_df = pd.concat([real_df] * 50, ignore_index=True)
        final_df = pd.concat([base_df, real_df], ignore_index=True)
        logger.info("Merged %d real EMS events into training set.", len(samples))
    else:
        final_df = base_df
        
    return final_df


# ---------------------------------------------------------------------------
# Hazard type classifier (post-hoc)
# ---------------------------------------------------------------------------

_HAZARD_THRESHOLDS = {
    "snowmelt": {"snow_cover": 0.35, "temp_trend": 4.0},
    "pluvial": {"rainfall_24h": 30.0},
    "fluvial": {"upstream_risk": 50.0, "ndwi": 0.1},
}


def _classify_hazard_type(features: FloodFeatures) -> tuple[str, str]:
    """Determine dominant hazard type and human-readable explanation.

    Returns (hazard_type, dominant_feature_description).
    """
    scores: dict[str, float] = {}

    # Snowmelt score
    if features.snow_cover > 0.35 and features.temp_trend > 4.0:
        scores["snowmelt"] = features.snow_cover * features.temp_trend
    elif features.snow_cover > 0.2:
        scores["snowmelt"] = features.snow_cover * 0.5

    # Pluvial score
    if features.rainfall_24h > 10:
        scores["pluvial"] = features.rainfall_24h / 50.0 + features.soil_moisture

    # Fluvial score
    if features.upstream_risk > 20 or features.ndwi > 0.0:
        scores["fluvial"] = (features.upstream_risk / 100.0) + max(features.ndwi, 0.0)

    if not scores:
        return "fluvial", "baseline risk — no dominant trigger"

    dominant = max(scores, key=lambda k: scores[k])

    descriptions = {
        "snowmelt": (
            f"snowmelt risk: FSC={features.snow_cover * 100:.0f}% + "
            f"ΔT={features.temp_trend:+.1f}°C"
        ),
        "pluvial": (
            f"heavy rain: {features.rainfall_24h:.0f} mm/24h + "
            f"soil sat.={features.soil_moisture:.2f}"
        ),
        "fluvial": (
            f"upstream risk={features.upstream_risk:.0f} + "
            f"NDWI={features.ndwi:.2f}"
        ),
    }
    return dominant, descriptions[dominant]


# ---------------------------------------------------------------------------
# Main classifier service
# ---------------------------------------------------------------------------


class FloodClassifier:
    """XGBoost flood probability classifier.

    The model is trained on first instantiation using synthetic data that
    encodes hydrological domain knowledge.  In production, replace
    ``_generate_synthetic_training_data()`` with a real feature-label
    join from the Copernicus EMS + Open-Meteo time-series database.

    Usage::

        clf = FloodClassifier()
        result = clf.predict(features)
        print(result.risk_score, result.hazard_type)
    """

    MODEL_VERSION = "xgb-v1.0"
    _MODEL_CACHE: Path = Path(__file__).parent / "_model_cache.json"

    def __init__(self) -> None:
        self._model = None
        self._feature_importances: dict[str, float] = {}
        self._train_accuracy: float = 0.0
        self._train()

    # ------------------------------------------------------------------ #
    # Training                                                            #
    # ------------------------------------------------------------------ #

    def _train(self) -> None:
        """Train XGBoost classifier on synthetic data."""
        try:
            import xgboost as xgb
            from sklearn.model_selection import train_test_split
            from sklearn.metrics import accuracy_score, roc_auc_score
        except ImportError as e:
            logger.error("ML dependencies not installed: %s", e)
            return

        logger.info("Training XGBoost flood classifier on Real + Synthetic data…")
        df = _build_real_training_data()

        X = df[FEATURE_COLUMNS].values
        y = df["is_flooded"].values

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        self._model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            use_label_encoder=False,
            eval_metric="logloss",
            random_state=42,
            verbosity=0,
        )
        self._model.fit(
            X_train,
            y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )

        y_pred = self._model.predict(X_test)
        y_proba = self._model.predict_proba(X_test)[:, 1]

        acc = accuracy_score(y_test, y_pred)
        auc = roc_auc_score(y_test, y_proba)
        self._train_accuracy = acc

        importances = self._model.feature_importances_
        self._feature_importances = {
            col: round(float(imp), 4)
            for col, imp in zip(FEATURE_COLUMNS, importances)
        }

        logger.info(
            "XGBoost trained: accuracy=%.3f, AUC=%.3f, features=%s",
            acc,
            auc,
            self._feature_importances,
        )

    # ------------------------------------------------------------------ #
    # Inference                                                           #
    # ------------------------------------------------------------------ #

    def predict(self, features: FloodFeatures) -> PredictionResult:
        """Run inference for a single NUTS region feature set.

        Falls back to a rule-based heuristic if the XGBoost model is
        unavailable (e.g., import failure).
        """
        if self._model is None:
            return self._heuristic_predict(features)

        fv = np.array([features.to_feature_vector()])
        proba = float(self._model.predict_proba(fv)[0, 1])
        hazard, dominant_feature = _classify_hazard_type(features)

        return PredictionResult(
            nuts_id=features.nuts_id,
            flood_probability=round(proba, 4),
            risk_score=round(proba * 100, 2),
            hazard_type=hazard,
            dominant_feature=dominant_feature,
            features_used=features.to_dict(),
            model_version=self.MODEL_VERSION,
        )

    def predict_batch(self, features_list: list[FloodFeatures]) -> list[PredictionResult]:
        """Run inference for multiple NUTS regions at once."""
        if self._model is None:
            return [self._heuristic_predict(f) for f in features_list]

        fv_matrix = np.array([f.to_feature_vector() for f in features_list])
        probas = self._model.predict_proba(fv_matrix)[:, 1]

        results = []
        for f, proba in zip(features_list, probas):
            hazard, dominant = _classify_hazard_type(f)
            results.append(
                PredictionResult(
                    nuts_id=f.nuts_id,
                    flood_probability=round(float(proba), 4),
                    risk_score=round(float(proba) * 100, 2),
                    hazard_type=hazard,
                    dominant_feature=dominant,
                    features_used=f.to_dict(),
                    model_version=self.MODEL_VERSION,
                )
            )
        return results

    # ------------------------------------------------------------------ #
    # Rule-based fallback                                                 #
    # ------------------------------------------------------------------ #

    def _heuristic_predict(self, features: FloodFeatures) -> PredictionResult:
        """Rule-based fallback when XGBoost is unavailable."""
        score = 0.0
        score += min(features.rainfall_24h / 100.0, 0.4)
        score += features.soil_moisture * 0.2
        score += max(features.ndwi, 0.0) * 0.2
        if features.snow_cover > 0.35 and features.temp_trend > 4.0:
            score += 0.35
        score += (features.upstream_risk / 100.0) * 0.2
        score = float(np.clip(score, 0.0, 1.0))

        hazard, dominant = _classify_hazard_type(features)
        return PredictionResult(
            nuts_id=features.nuts_id,
            flood_probability=round(score, 4),
            risk_score=round(score * 100, 2),
            hazard_type=hazard,
            dominant_feature=dominant,
            features_used=features.to_dict(),
            model_version="heuristic-fallback",
        )

    # ------------------------------------------------------------------ #
    # Introspection                                                       #
    # ------------------------------------------------------------------ #

    def feature_importances(self) -> dict[str, float]:
        """Return XGBoost feature importances (gain-based)."""
        return dict(self._feature_importances)

    def model_info(self) -> dict[str, Any]:
        """Return a summary of the trained model."""
        return {
            "model_version": self.MODEL_VERSION,
            "algorithm": "XGBClassifier",
            "features": FEATURE_COLUMNS,
            "train_accuracy": round(self._train_accuracy, 4),
            "feature_importances": self._feature_importances,
            "hazard_types": ["fluvial", "pluvial", "snowmelt"],
            "available": self._model is not None,
        }
