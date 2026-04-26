import json
import os
import random

NUTS_REGIONS = []
INFRASTRUCTURE = []

_GEOJSON_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "frontend", "public", "nuts_regions.geojson"
)

# A set of regions that we want to prioritize for the "Bad Weather" demo
# We include historically flood-prone regions: Emilia-Romagna (ITH5), Valencia (ES52),
# Thessaly (EL61), Liege (BE33), Ahrweiler/Koblenz (DEB1), Veneto (ITH3)
DEMO_TARGETS = {
    "RO224", "RO221", "RO216", "RO121", "RO213", "RO321", "FR101", "DEA23", "ITC4C", "AT130", "CZ010", "HU110",
    "ES511", "NL226", "NL341", "BG311", "EL301",
    "ITH5", "ES52", "EL61", "BE33", "DEB1", "ITH3"
}

def load_all_regions():
    global NUTS_REGIONS, INFRASTRUCTURE
    if NUTS_REGIONS:
        return
        
    try:
        with open(_GEOJSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            nuts_id = props.get("NUTS_ID", "")
            if not nuts_id:
                continue
                
            name = props.get("NUTS_NAME", props.get("NAME_LATN", "Unknown"))
            
            geom = feature.get("geometry") or {}
            coords = geom.get("coordinates") or []
            
            def extract_points(coords):
                if not isinstance(coords, list): return
                if len(coords) == 2 and isinstance(coords[0], (int, float)):
                    yield coords
                else:
                    for item in coords:
                        yield from extract_points(item)
            
            min_lon, min_lat, max_lon, max_lat = 180, 90, -180, -90
            point_count = 0
            
            for lon, lat in extract_points(coords):
                min_lon = min(min_lon, lon)
                max_lon = max(max_lon, lon)
                min_lat = min(min_lat, lat)
                max_lat = max(max_lat, lat)
                point_count += 1
                
            if point_count == 0:
                continue
                
            center_lon = (min_lon + max_lon) / 2
            center_lat = (min_lat + max_lat) / 2
            
            NUTS_REGIONS.append({
                "nuts_id": nuts_id,
                "name": name,
                "level": 3,
                "population": props.get("POPULATION", random.randint(50000, 500000)),
                "latitude": center_lat,
                "longitude": center_lon,
                "bbox": (min_lon, min_lat, max_lon, max_lat)
            })
            
            # Generate fake infrastructure for most regions (70% chance), but guarantee it for DEMO_TARGETS
            if nuts_id in DEMO_TARGETS or random.random() > 0.3:
                INFRASTRUCTURE.append({
                    "nuts_id": nuts_id,
                    "type": "hospital",
                    "name": f"Hospital {name}",
                    "latitude": center_lat + random.uniform(-0.01, 0.01),
                    "longitude": center_lon + random.uniform(-0.01, 0.01)
                })
                # 50% chance to also have a school
                if random.random() > 0.5:
                    INFRASTRUCTURE.append({
                        "nuts_id": nuts_id,
                        "type": "school",
                        "name": f"High School {name}",
                        "latitude": center_lat + random.uniform(-0.01, 0.01),
                        "longitude": center_lon + random.uniform(-0.01, 0.01)
                    })

    except Exception as e:
        print(f"Error loading eu regions: {e}")

# Load them on import
load_all_regions()
