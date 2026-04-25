"""HydroNetwork Service — Task 4, Step 3.

Builds a directed hydrographic graph from EU-Hydro / HydroSHEDS vector data
so that the GNN / ML engine can model river-flow propagation (upstream risk
propagates downstream).

Architecture
------------
• Nodes  → river segments identified by a ``reach_id``
• Edges  → directed from upstream to downstream (``from_id → to_id``)
• Attributes on each node:
    - nuts_id    : NUTS-3 region the segment belongs to
    - stream_order : Strahler order (larger = major river)
    - length_km  : segment length

Data sources (priority order)
------------------------------
1. ``backend/data/hydrosheds_ro.geojson``  — user-supplied pre-download
2. Built-in synthetic graph for the Bârlad → Siret → Danube corridor,
   which covers the Romanian regions in the EMS ground-truth dataset.

Production upgrade
------------------
Download EU-Hydro from:
  https://land.copernicus.eu/imagery-in-situ/eu-hydro/eu-hydro-river-network-database

Or HydroSHEDS from:
  https://www.hydrosheds.org/products/hydrorivers

Then convert to GeoJSON and save to ``backend/data/hydrosheds_ro.geojson``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in synthetic hydrographic network (Bârlad → Siret → Dunăre corridor)
# Covers NUTS-3 regions: RO224 (Galați), RO221 (Brăila), RO225 (Tulcea)
# and neighbouring upstream regions.
# ---------------------------------------------------------------------------

_BUILTIN_NODES: list[dict[str, Any]] = [
    # Upstream Bârlad basin
    {"reach_id": "RO_BARLAD_U1", "nuts_id": "RO216", "name": "Bârlad (upper)", "stream_order": 3, "length_km": 45.0, "lat": 46.5, "lon": 27.7},
    {"reach_id": "RO_BARLAD_U2", "nuts_id": "RO216", "name": "Bârlad (mid)",   "stream_order": 4, "length_km": 60.0, "lat": 46.1, "lon": 27.6},
    # Bârlad lower → Siret confluence
    {"reach_id": "RO_BARLAD_L1", "nuts_id": "RO224", "name": "Bârlad (lower)", "stream_order": 4, "length_km": 55.0, "lat": 45.7, "lon": 27.7},
    # Siret (major river)
    {"reach_id": "RO_SIRET_U1",  "nuts_id": "RO211", "name": "Siret (upper)",  "stream_order": 5, "length_km": 80.0, "lat": 46.9, "lon": 26.9},
    {"reach_id": "RO_SIRET_M1",  "nuts_id": "RO213", "name": "Siret (mid)",    "stream_order": 5, "length_km": 90.0, "lat": 46.3, "lon": 27.0},
    {"reach_id": "RO_SIRET_L1",  "nuts_id": "RO224", "name": "Siret (lower)",  "stream_order": 6, "length_km": 75.0, "lat": 45.5, "lon": 27.6},
    # Prut river
    {"reach_id": "RO_PRUT_L1",   "nuts_id": "RO213", "name": "Prut (lower)",   "stream_order": 5, "length_km": 100.0,"lat": 46.0, "lon": 28.1},
    # Danube (Dunăre)
    {"reach_id": "RO_DANUBE_U1", "nuts_id": "RO221", "name": "Danube (upper Brăila)", "stream_order": 9, "length_km": 120.0,"lat": 45.3, "lon": 28.0},
    {"reach_id": "RO_DANUBE_D1", "nuts_id": "RO225", "name": "Danube Delta",           "stream_order": 9, "length_km": 150.0,"lat": 45.0, "lon": 29.2},
]

_BUILTIN_EDGES: list[tuple[str, str]] = [
    # Bârlad internal flow
    ("RO_BARLAD_U1", "RO_BARLAD_U2"),
    ("RO_BARLAD_U2", "RO_BARLAD_L1"),
    # Bârlad flows into Siret
    ("RO_BARLAD_L1", "RO_SIRET_L1"),
    # Siret internal flow
    ("RO_SIRET_U1", "RO_SIRET_M1"),
    ("RO_SIRET_M1", "RO_SIRET_L1"),
    # Prut joins Danube
    ("RO_PRUT_L1", "RO_DANUBE_U1"),
    # Siret lower → Danube
    ("RO_SIRET_L1", "RO_DANUBE_U1"),
    # Danube flows to delta
    ("RO_DANUBE_U1", "RO_DANUBE_D1"),
]


# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------


@dataclass
class RiverSegment:
    reach_id: str
    nuts_id: str
    name: str
    stream_order: int
    length_km: float
    lat: float
    lon: float


@dataclass
class DownstreamPath:
    """Result of a downstream propagation query."""

    origin_reach_id: str
    path: list[str]           # ordered list of reach_ids from origin to outlet
    nuts_ids: list[str]       # unique NUTS regions along the path (in order)
    total_length_km: float


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class HydroNetworkService:
    """Directed hydrographic graph built from EU-Hydro / HydroSHEDS.

    Usage::

        svc = HydroNetworkService()
        path = svc.get_downstream_path("RO_BARLAD_U1")
        print(path.nuts_ids)   # ['RO216', 'RO224', 'RO221', 'RO225']
    """

    _DATA_FILE = Path(__file__).parents[3] / "data" / "hydrosheds_ro.geojson"

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()
        self._segments: dict[str, RiverSegment] = {}
        self._build_graph()

    # ------------------------------------------------------------------ #
    # Graph construction                                                  #
    # ------------------------------------------------------------------ #

    def _build_graph(self) -> None:
        """Load hydrographic data and build the directed graph."""
        if self._DATA_FILE.exists():
            self._load_from_geojson(self._DATA_FILE)
        else:
            logger.info(
                "HydroSHEDS GeoJSON not found at %s — using built-in synthetic network",
                self._DATA_FILE,
            )
            self._load_builtin()

        logger.info(
            "HydroNetworkService: %d nodes, %d edges loaded",
            self._graph.number_of_nodes(),
            self._graph.number_of_edges(),
        )

    def _load_builtin(self) -> None:
        """Populate graph from the hard-coded Bârlad→Siret→Danube data."""
        for node_data in _BUILTIN_NODES:
            seg = RiverSegment(
                reach_id=node_data["reach_id"],
                nuts_id=node_data["nuts_id"],
                name=node_data["name"],
                stream_order=node_data["stream_order"],
                length_km=node_data["length_km"],
                lat=node_data["lat"],
                lon=node_data["lon"],
            )
            self._segments[seg.reach_id] = seg
            self._graph.add_node(
                seg.reach_id,
                nuts_id=seg.nuts_id,
                name=seg.name,
                stream_order=seg.stream_order,
                length_km=seg.length_km,
                lat=seg.lat,
                lon=seg.lon,
            )

        for from_id, to_id in _BUILTIN_EDGES:
            self._graph.add_edge(from_id, to_id)

    def _load_from_geojson(self, path: Path) -> None:
        """Load a GeoJSON FeatureCollection of LineString river segments.

        Expected properties per feature:
            reach_id, nuts_id, name, stream_order, length_km, to_reach_id
        """
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            logger.error("Failed to load %s: %s — falling back to built-in", path, exc)
            self._load_builtin()
            return

        features = data.get("features", [])
        for feat in features:
            props = feat.get("properties", {})
            reach_id = props.get("reach_id")
            if not reach_id:
                continue
            coords = feat.get("geometry", {}).get("coordinates", [[0, 0]])
            mid = coords[len(coords) // 2] if coords else [0, 0]
            seg = RiverSegment(
                reach_id=reach_id,
                nuts_id=props.get("nuts_id", ""),
                name=props.get("name", reach_id),
                stream_order=int(props.get("stream_order", 3)),
                length_km=float(props.get("length_km", 0)),
                lat=mid[1],
                lon=mid[0],
            )
            self._segments[reach_id] = seg
            self._graph.add_node(
                reach_id,
                **{k: getattr(seg, k) for k in seg.__dataclass_fields__},
            )

        # Add directed edges using to_reach_id property
        for feat in features:
            props = feat.get("properties", {})
            from_id = props.get("reach_id")
            to_id = props.get("to_reach_id")
            if from_id and to_id and to_id in self._graph:
                self._graph.add_edge(from_id, to_id)

        if self._graph.number_of_nodes() == 0:
            logger.warning("GeoJSON produced empty graph — falling back to built-in")
            self._load_builtin()

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    @property
    def graph(self) -> nx.DiGraph:
        """The underlying NetworkX directed graph."""
        return self._graph

    def get_segment(self, reach_id: str) -> RiverSegment | None:
        """Return segment metadata by reach_id."""
        return self._segments.get(reach_id)

    def get_nuts_reaches(self, nuts_id: str) -> list[RiverSegment]:
        """Return all river segments within a NUTS-3 region."""
        return [s for s in self._segments.values() if s.nuts_id == nuts_id]

    def get_downstream_path(self, origin_reach_id: str) -> DownstreamPath | None:
        """Trace the downstream path from a reach to the river outlet.

        Uses DFS on the directed graph.  The outlet node is any node
        with out-degree == 0.

        Returns ``None`` if the origin node is not in the graph.
        """
        if origin_reach_id not in self._graph:
            logger.warning("Reach '%s' not in graph", origin_reach_id)
            return None

        path: list[str] = [origin_reach_id]
        visited: set[str] = {origin_reach_id}
        current = origin_reach_id

        while True:
            successors = list(self._graph.successors(current))
            # Filter already-visited to avoid cycles (data quality)
            next_nodes = [n for n in successors if n not in visited]
            if not next_nodes:
                break
            current = next_nodes[0]  # follow first successor (largest stream)
            visited.add(current)
            path.append(current)

        # Collect unique NUTS IDs in traversal order
        seen_nuts: list[str] = []
        for rid in path:
            nid = self._graph.nodes[rid].get("nuts_id", "")
            if nid and (not seen_nuts or seen_nuts[-1] != nid):
                seen_nuts.append(nid)

        total_km = sum(
            self._graph.nodes[rid].get("length_km", 0) for rid in path
        )

        return DownstreamPath(
            origin_reach_id=origin_reach_id,
            path=path,
            nuts_ids=seen_nuts,
            total_length_km=round(total_km, 2),
        )

    def get_upstream_risk_propagation(
        self, nuts_id: str, risk_score: float
    ) -> dict[str, float]:
        """Propagate a risk score from all reaches in a NUTS region downstream.

        Returns a dict mapping affected downstream ``nuts_id → propagated_risk``.
        Risk attenuates by 20 % per hop (simple exponential decay model).

        This is the GNN-lite logic used in Task 5 as a structural prior.
        """
        ATTENUATION = 0.80  # risk kept per hop

        propagated: dict[str, float] = {}
        starts = self.get_nuts_reaches(nuts_id)

        for seg in starts:
            path_result = self.get_downstream_path(seg.reach_id)
            if not path_result:
                continue
            current_risk = risk_score
            for hop, rid in enumerate(path_result.path[1:], start=1):
                current_risk *= ATTENUATION
                downstream_nuts = self._graph.nodes[rid].get("nuts_id", "")
                if downstream_nuts and downstream_nuts != nuts_id:
                    existing = propagated.get(downstream_nuts, 0.0)
                    propagated[downstream_nuts] = max(existing, current_risk)

        return {k: round(v, 2) for k, v in propagated.items()}

    def summary(self) -> dict[str, Any]:
        """Return a human-readable network summary."""
        nuts_coverage: set[str] = {
            data.get("nuts_id", "")
            for _, data in self._graph.nodes(data=True)
        }
        return {
            "nodes": self._graph.number_of_nodes(),
            "edges": self._graph.number_of_edges(),
            "nuts_regions_covered": sorted(nuts_coverage - {""}),
            "outlet_nodes": [
                n for n in self._graph.nodes
                if self._graph.out_degree(n) == 0
            ],
            "source": "hydrosheds_ro.geojson" if self._DATA_FILE.exists() else "built-in synthetic",
        }
