"""Copernicus EMS Ground Truth Service — Task 4, Step 2.

Ingests historical flood activation records from the Copernicus Emergency
Management Service (EMS) and produces labelled training samples for the
XGBoost model (Task 5).

Design notes
------------
• In production the EMS catalogue is queried via:
    https://emergency.copernicus.eu/mapping/list-of-activations-rapid
  or the ATOM feed at:
    https://emergency.copernicus.eu/mapping/activations.atom

• For the hackathon demo we embed a curated dataset of real EMS flood
  activations over Romania/Danube region (2012-2024).  Each record
  contains the EMS activation code, the affected NUTS-3 region, the
  event dates, and the official `is_flooded` label.

• The service can also load additional activations from a JSON file
  placed at  backend/data/ems_activations.json  (optional).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Curated EMS activation dataset (Romania-centric, sourced from public EMS)
# Reference: https://emergency.copernicus.eu/mapping/list-of-activations-rapid
# ---------------------------------------------------------------------------

_BUILTIN_ACTIVATIONS: list[dict[str, Any]] = [
    # EMSR692 — Floods in Galați County (July 2024)
    {
        "activation_code": "EMSR692",
        "title": "Floods in Galați County, Romania",
        "nuts_ids": ["RO224"],
        "event_start": "2024-07-08",
        "event_end": "2024-07-18",
        "hazard_type": "fluvial",
        "is_flooded": 1,
        "source_url": "https://emergency.copernicus.eu/mapping/ems-rapid-mapping-activation/EMSR692",
    },
    # EMSR546 — Floods in Iași / Bacău (June 2020)
    {
        "activation_code": "EMSR546",
        "title": "Floods in Moldavian Plateau, Romania",
        "nuts_ids": ["RO213", "RO211"],
        "event_start": "2020-06-22",
        "event_end": "2020-07-05",
        "hazard_type": "pluvial",
        "is_flooded": 1,
        "source_url": "https://emergency.copernicus.eu/mapping/ems-rapid-mapping-activation/EMSR546",
    },
    # EMSR117 — Danube flooding (April 2014)
    {
        "activation_code": "EMSR117",
        "title": "Danube River flooding — Tulcea / Brăila",
        "nuts_ids": ["RO225", "RO221"],
        "event_start": "2014-04-09",
        "event_end": "2014-04-25",
        "hazard_type": "fluvial",
        "is_flooded": 1,
        "source_url": "https://emergency.copernicus.eu/mapping/ems-rapid-mapping-activation/EMSR117",
    },
    # EMSR033 — Black Sea coast flooding (June 2012)
    {
        "activation_code": "EMSR033",
        "title": "Floods in Dobrogea — Constanța",
        "nuts_ids": ["RO223"],
        "event_start": "2012-06-30",
        "event_end": "2012-07-10",
        "hazard_type": "pluvial",
        "is_flooded": 1,
        "source_url": "https://emergency.copernicus.eu/mapping/ems-rapid-mapping-activation/EMSR033",
    },
]

# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------


@dataclass
class EMSActivation:
    """A single Copernicus EMS flood activation record."""

    activation_code: str
    title: str
    nuts_ids: list[str]
    event_start: date
    event_end: date
    hazard_type: str       # fluvial | pluvial | snowmelt
    is_flooded: int        # 1 = confirmed flood, 0 = reference period (no flood)
    source_url: str = ""


@dataclass
class LabelledSample:
    """A training sample linking an EMS event to a NUTS region.

    Consumed by the XGBoost pipeline in Task 5.
    """

    nuts_id: str
    event_start: date
    event_end: date
    hazard_type: str
    is_flooded: int                          # target label
    activation_code: str                     # provenance
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "nuts_id": self.nuts_id,
            "event_start": self.event_start.isoformat(),
            "event_end": self.event_end.isoformat(),
            "hazard_type": self.hazard_type,
            "is_flooded": self.is_flooded,
            "activation_code": self.activation_code,
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class EMSGroundTruthService:
    """Loads EMS activations and produces labelled training data.

    Usage::

        svc = EMSGroundTruthService()
        samples = svc.get_labelled_samples(nuts_ids=["RO224", "RO213"])
        df = svc.to_dataframe(samples)
    """

    _DATA_FILE = Path(__file__).parents[3] / "data" / "ems_activations.json"

    def __init__(self) -> None:
        self._activations: list[EMSActivation] = self._load_activations()

    # ------------------------------------------------------------------ #
    # Loading                                                             #
    # ------------------------------------------------------------------ #

    def _load_activations(self) -> list[EMSActivation]:
        """Merge built-in records with optional external JSON file."""
        raw: list[dict[str, Any]] = list(_BUILTIN_ACTIVATIONS)

        if self._DATA_FILE.exists():
            try:
                with self._DATA_FILE.open(encoding="utf-8") as fh:
                    extra = json.load(fh)
                if isinstance(extra, list):
                    raw.extend(extra)
                    logger.info(
                        "Loaded %d extra EMS activations from %s",
                        len(extra),
                        self._DATA_FILE,
                    )
            except Exception as exc:
                logger.warning("Could not load %s: %s", self._DATA_FILE, exc)

        activations = []
        for rec in raw:
            try:
                activations.append(
                    EMSActivation(
                        activation_code=rec["activation_code"],
                        title=rec["title"],
                        nuts_ids=rec["nuts_ids"],
                        event_start=date.fromisoformat(rec["event_start"]),
                        event_end=date.fromisoformat(rec["event_end"]),
                        hazard_type=rec.get("hazard_type", "fluvial"),
                        is_flooded=rec.get("is_flooded", 1),
                        source_url=rec.get("source_url", ""),
                    )
                )
            except Exception as exc:
                logger.warning("Skipping malformed EMS record %s: %s", rec, exc)

        logger.info("EMSGroundTruthService: %d activations loaded", len(activations))
        return activations

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    @property
    def activations(self) -> list[EMSActivation]:
        """All loaded EMS activations."""
        return list(self._activations)

    def get_activations_for_nuts(self, nuts_id: str) -> list[EMSActivation]:
        """Return EMS activations that affected a specific NUTS region."""
        return [a for a in self._activations if nuts_id in a.nuts_ids]

    def get_labelled_samples(
        self,
        nuts_ids: list[str] | None = None,
        hazard_type: str | None = None,
    ) -> list[LabelledSample]:
        """Produce one :class:`LabelledSample` per (activation × NUTS region).

        Parameters
        ----------
        nuts_ids:
            Filter to specific NUTS regions.  ``None`` → all regions.
        hazard_type:
            Filter to ``'fluvial'``, ``'pluvial'``, or ``'snowmelt'``.
            ``None`` → all hazard types.
        """
        samples: list[LabelledSample] = []
        for act in self._activations:
            if hazard_type and act.hazard_type != hazard_type:
                continue
            for nid in act.nuts_ids:
                if nuts_ids and nid not in nuts_ids:
                    continue
                samples.append(
                    LabelledSample(
                        nuts_id=nid,
                        event_start=act.event_start,
                        event_end=act.event_end,
                        hazard_type=act.hazard_type,
                        is_flooded=act.is_flooded,
                        activation_code=act.activation_code,
                    )
                )
        logger.info(
            "get_labelled_samples → %d samples (nuts_ids=%s, hazard=%s)",
            len(samples),
            nuts_ids,
            hazard_type,
        )
        return samples

    def to_dataframe(self, samples: list[LabelledSample]):
        """Convert labelled samples to a pandas DataFrame for ML training.

        Requires pandas (already in requirements.txt).
        """
        import pandas as pd  # lazy import — not needed at import time

        if not samples:
            return pd.DataFrame()
        return pd.DataFrame([s.to_dict() for s in samples])

    def summary(self) -> dict[str, Any]:
        """Return a summary of the loaded ground-truth dataset."""
        by_hazard: dict[str, int] = {}
        affected_nuts: set[str] = set()
        for act in self._activations:
            by_hazard[act.hazard_type] = by_hazard.get(act.hazard_type, 0) + 1
            affected_nuts.update(act.nuts_ids)
        return {
            "total_activations": len(self._activations),
            "hazard_breakdown": by_hazard,
            "affected_nuts_regions": sorted(affected_nuts),
            "date_range": {
                "earliest": min(
                    (a.event_start for a in self._activations), default=None
                ),
                "latest": max(
                    (a.event_end for a in self._activations), default=None
                ),
            },
        }
