"""Risk Wave Propagator — Task 5, Step 1 (GNN-lite).

Implements spatial-temporal flood risk propagation on the hydrographic
graph built by :mod:`app.services.hydro_network`.

Physics model
-------------
A flood event at an upstream NUTS node A (with risk score R_A) propagates
downstream through the river network as a "risk wave":

    R_B(t + Δt) = R_A × decay^hops × temporal_boost(month)

Where:
  • decay      = 0.80 per graph hop (20 % attenuation per reach)
  • Δt per hop = length_km / flow_speed_kmh  (default 12 km/h)
  • temporal_boost: winter/spring months amplify risk (snowmelt overlay)

Demo scenario (Fallback Plan from Task 5, Step 3)
--------------------------------------------------
Tecuci (RO216) → Liești reach (RO224) → Galați (RO224) → Danube (RO221)

Querying::

    propagator = RiskPropagator(hydro_svc)
    waves = propagator.propagate(
        origin_nuts_id="RO216",
        initial_risk=85.0,
        rainfall_override_mm=200.0,
    )
    # Returns list[RiskWave] — one per affected downstream NUTS node
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.hydro_network import HydroNetworkService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_FLOW_SPEED_KMH = 12.0    # river flow speed (km/h) for travel time
_ATTENUATION_PER_HOP = 0.80       # risk kept per downstream hop
_MAX_PROPAGATION_HOPS = 10        # safety guard against infinite traversal

# Seasonal amplification for snowmelt months (March-May)
_SEASONAL_BOOST: dict[int, float] = {
    3: 1.15,   # March — snowmelt onset
    4: 1.25,   # April — peak snowmelt
    5: 1.10,   # May   — lingering melt
    6: 1.05,   # June  — early summer storms
    11: 1.05,  # November — autumn rains
    12: 1.05,  # December — early winter
}


# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------


@dataclass
class RiskWave:
    """A downstream risk wave reaching a specific NUTS region.

    ``delay_hours`` is the estimated travel time from the origin reach to
    this node, calculated from segment lengths and flow speed.
    """

    nuts_id: str
    risk_score: float               # 0-100 (attenuated from origin)
    delay_hours: float              # estimated travel time from origin
    hops: int                       # number of graph hops from origin
    via_reach_ids: list[str]        # ordered reach path from origin
    seasonal_boost_applied: bool    # True if spring/autumn amplification used
    origin_nuts_id: str             # source of the risk wave
    computed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "nuts_id": self.nuts_id,
            "risk_score": self.risk_score,
            "delay_hours": self.delay_hours,
            "hops": self.hops,
            "via_reach_ids": self.via_reach_ids,
            "seasonal_boost_applied": self.seasonal_boost_applied,
            "origin_nuts_id": self.origin_nuts_id,
            "computed_at": self.computed_at,
        }


@dataclass
class PropagationResult:
    """Complete risk propagation result from an upstream origin."""

    origin_nuts_id: str
    initial_risk: float
    month: int
    seasonal_boost: float
    waves: list[RiskWave]
    total_affected_nuts: int
    max_downstream_risk: float
    computed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin_nuts_id": self.origin_nuts_id,
            "initial_risk": self.initial_risk,
            "month": self.month,
            "seasonal_boost": self.seasonal_boost,
            "waves": [w.to_dict() for w in self.waves],
            "total_affected_nuts": self.total_affected_nuts,
            "max_downstream_risk": self.max_downstream_risk,
            "computed_at": self.computed_at,
        }


# ---------------------------------------------------------------------------
# Demo scenario data
# ---------------------------------------------------------------------------

# Hard-coded Tecuci → Galați demo corridor for Step 3 fallback
_DEMO_SCENARIO_NODES = [
    {"nuts_id": "RO216", "name": "Tecuci / Vaslui",  "reach_id": "RO_BARLAD_U1", "km_from_origin": 0.0},
    {"nuts_id": "RO216", "name": "Bârlad (mid)",     "reach_id": "RO_BARLAD_U2", "km_from_origin": 45.0},
    {"nuts_id": "RO224", "name": "Bârlad → Galați",  "reach_id": "RO_BARLAD_L1", "km_from_origin": 105.0},
    {"nuts_id": "RO224", "name": "Siret–Galați confluence", "reach_id": "RO_SIRET_L1", "km_from_origin": 180.0},
    {"nuts_id": "RO221", "name": "Danube / Brăila",  "reach_id": "RO_DANUBE_U1", "km_from_origin": 300.0},
    {"nuts_id": "RO225", "name": "Danube Delta / Tulcea", "reach_id": "RO_DANUBE_D1", "km_from_origin": 450.0},
]


# ---------------------------------------------------------------------------
# Risk Propagator
# ---------------------------------------------------------------------------


class RiskPropagator:
    """Graph-based flood risk wave propagator (GNN-lite).

    Parameters
    ----------
    hydro_svc:
        A live :class:`~app.services.hydro_network.HydroNetworkService`
        instance.  If ``None``, the propagator uses the hard-coded demo
        scenario corridor.
    flow_speed_kmh:
        Mean river flow speed used to estimate downstream travel times.
        Default: 12 km/h (typical medium-sized Romanian river).
    attenuation:
        Fraction of risk retained per downstream graph hop (0-1).
        Default: 0.80 (20 % decay per reach).

    Usage::

        from app.services.hydro_network import HydroNetworkService
        hydro = HydroNetworkService()
        propagator = RiskPropagator(hydro)
        result = propagator.propagate("RO216", initial_risk=85.0)
    """

    def __init__(
        self,
        hydro_svc: "HydroNetworkService | None" = None,
        flow_speed_kmh: float = _DEFAULT_FLOW_SPEED_KMH,
        attenuation: float = _ATTENUATION_PER_HOP,
    ) -> None:
        self._hydro = hydro_svc
        self._flow_speed = flow_speed_kmh
        self._attenuation = attenuation

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def propagate(
        self,
        origin_nuts_id: str,
        initial_risk: float,
        rainfall_override_mm: float | None = None,
        month: int | None = None,
    ) -> PropagationResult:
        """Propagate a risk wave downstream from an origin NUTS region.

        Parameters
        ----------
        origin_nuts_id:
            NUTS-3 ID of the region where the flood event originates.
        initial_risk:
            Risk score at the origin node (0-100).
        rainfall_override_mm:
            If provided, boosts initial_risk by up to 20 % for extreme
            rainfall events (>100 mm).  Simulates the demo slider from
            Task 5, Step 3.
        month:
            Calendar month (1-12).  Defaults to current UTC month.
            Used to apply seasonal snowmelt amplification.
        """
        if month is None:
            month = datetime.now(timezone.utc).month

        # Apply rainfall boost
        if rainfall_override_mm is not None and rainfall_override_mm > 50:
            rain_boost = min((rainfall_override_mm - 50) / 250.0, 0.20)
            initial_risk = min(100.0, initial_risk * (1.0 + rain_boost))
            logger.info(
                "Rainfall override %.0f mm → risk boosted to %.1f",
                rainfall_override_mm,
                initial_risk,
            )

        seasonal_boost = _SEASONAL_BOOST.get(month, 1.0)

        if self._hydro is not None:
            waves = self._propagate_graph(origin_nuts_id, initial_risk, seasonal_boost)
        else:
            waves = self._propagate_demo(origin_nuts_id, initial_risk, seasonal_boost)

        # Sort by delay
        waves.sort(key=lambda w: w.delay_hours)

        affected_nuts = list({w.nuts_id for w in waves})
        max_risk = max((w.risk_score for w in waves), default=0.0)

        return PropagationResult(
            origin_nuts_id=origin_nuts_id,
            initial_risk=round(initial_risk, 2),
            month=month,
            seasonal_boost=seasonal_boost,
            waves=waves,
            total_affected_nuts=len(affected_nuts),
            max_downstream_risk=round(max_risk, 2),
        )

    def propagate_multi(
        self,
        origins: dict[str, float],   # nuts_id → risk_score
        month: int | None = None,
    ) -> dict[str, float]:
        """Propagate risks from multiple origins and return merged downstream risks.

        Returns a flat dict mapping downstream NUTS IDs to their maximum
        risk from any upstream source.  Useful for the batch prediction
        endpoint.
        """
        merged: dict[str, float] = {}
        for nuts_id, risk in origins.items():
            result = self.propagate(nuts_id, risk, month=month)
            for wave in result.waves:
                existing = merged.get(wave.nuts_id, 0.0)
                merged[wave.nuts_id] = max(existing, wave.risk_score)
        return {k: round(v, 2) for k, v in merged.items()}

    # ------------------------------------------------------------------ #
    # Graph-based propagation                                             #
    # ------------------------------------------------------------------ #

    def _propagate_graph(
        self,
        origin_nuts_id: str,
        initial_risk: float,
        seasonal_boost: float,
    ) -> list[RiskWave]:
        """BFS risk propagation over the HydroNetworkService graph."""
        waves: list[RiskWave] = []
        reached: dict[str, float] = {}  # reach_id → best risk seen

        starts = self._hydro.get_nuts_reaches(origin_nuts_id)
        if not starts:
            logger.warning("No reaches found for NUTS '%s'", origin_nuts_id)
            return []

        # BFS queue: (reach_id, current_risk, hops, path, km_from_origin)
        from collections import deque
        queue: deque[tuple[str, float, int, list[str], float]] = deque()

        for seg in starts:
            queue.append((seg.reach_id, initial_risk, 0, [seg.reach_id], 0.0))
            reached[seg.reach_id] = initial_risk

        # Nuts-level tracking: best risk wave per NUTS
        nuts_best: dict[str, RiskWave] = {}

        graph = self._hydro.graph

        while queue:
            reach_id, risk, hops, path, total_km = queue.popleft()

            if hops > _MAX_PROPAGATION_HOPS:
                continue

            for successor in graph.successors(reach_id):
                seg_data = graph.nodes.get(successor, {})
                hop_km = seg_data.get("length_km", 20.0)
                downstream_nuts = seg_data.get("nuts_id", "")

                new_km = total_km + hop_km
                new_risk = risk * self._attenuation

                # Apply seasonal boost for downstream nodes
                boosted_risk = min(100.0, new_risk * seasonal_boost)
                boosted_risk = round(boosted_risk, 2)

                # Skip already-visited with better risk
                if reached.get(successor, -1) >= boosted_risk:
                    continue
                reached[successor] = boosted_risk

                delay_h = round(new_km / self._flow_speed, 2)
                new_path = path + [successor]

                if downstream_nuts and downstream_nuts != origin_nuts_id:
                    wave = RiskWave(
                        nuts_id=downstream_nuts,
                        risk_score=boosted_risk,
                        delay_hours=delay_h,
                        hops=hops + 1,
                        via_reach_ids=new_path,
                        seasonal_boost_applied=seasonal_boost > 1.0,
                        origin_nuts_id=origin_nuts_id,
                    )
                    existing = nuts_best.get(downstream_nuts)
                    if existing is None or boosted_risk > existing.risk_score:
                        nuts_best[downstream_nuts] = wave

                queue.append((successor, new_risk, hops + 1, new_path, new_km))

        waves = list(nuts_best.values())
        logger.info(
            "Graph propagation from %s: %d downstream NUTS affected",
            origin_nuts_id,
            len(waves),
        )
        return waves

    # ------------------------------------------------------------------ #
    # Demo scenario (Step 3 fallback)                                     #
    # ------------------------------------------------------------------ #

    def _propagate_demo(
        self,
        origin_nuts_id: str,
        initial_risk: float,
        seasonal_boost: float,
    ) -> list[RiskWave]:
        """Hard-coded demo propagation for Tecuci → Galați → Danube corridor."""
        waves: list[RiskWave] = []
        current_risk = initial_risk
        origin_found = False

        for i, node in enumerate(_DEMO_SCENARIO_NODES):
            if node["nuts_id"] == origin_nuts_id:
                origin_found = True
                continue

            if not origin_found:
                continue

            # Propagate from origin
            hops = i
            current_risk = initial_risk * (self._attenuation ** hops)
            boosted = min(100.0, current_risk * seasonal_boost)
            delay_h = node["km_from_origin"] / self._flow_speed

            wave = RiskWave(
                nuts_id=node["nuts_id"],
                risk_score=round(boosted, 2),
                delay_hours=round(delay_h, 2),
                hops=hops,
                via_reach_ids=[n["reach_id"] for n in _DEMO_SCENARIO_NODES[:i + 1]],
                seasonal_boost_applied=seasonal_boost > 1.0,
                origin_nuts_id=origin_nuts_id,
            )
            waves.append(wave)

        if not origin_found:
            # Default: use Tecuci as origin
            return self._propagate_demo("RO216", initial_risk, seasonal_boost)

        # De-duplicate by nuts_id (keep highest risk)
        best: dict[str, RiskWave] = {}
        for w in waves:
            existing = best.get(w.nuts_id)
            if existing is None or w.risk_score > existing.risk_score:
                best[w.nuts_id] = w

        logger.info(
            "Demo propagation from %s: %d downstream nodes",
            origin_nuts_id,
            len(best),
        )
        return list(best.values())

    # ------------------------------------------------------------------ #
    # Introspection                                                       #
    # ------------------------------------------------------------------ #

    def info(self) -> dict[str, Any]:
        """Return propagator configuration summary."""
        return {
            "flow_speed_kmh": self._flow_speed,
            "attenuation_per_hop": self._attenuation,
            "max_propagation_hops": _MAX_PROPAGATION_HOPS,
            "seasonal_boosts": _SEASONAL_BOOST,
            "mode": "graph" if self._hydro is not None else "demo-scenario",
        }
