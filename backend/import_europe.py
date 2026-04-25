import json
import os
import sys

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.location import Location

def import_nuts3():
    geojson_path = os.path.join("..", "frontend", "public", "nuts_regions.geojson")
    if not os.path.exists(geojson_path):
        print(f"Error: {geojson_path} not found! Cannot import regions.")
        return

    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    db = SessionLocal()
    print(f"Reading geojson from {geojson_path}...")
    
    # Delete existing locations to ensure clean import
    db.query(Location).delete()
    db.commit()
    print("Cleared existing locations for fresh import.")

    count = 0
    features = data.get("features", [])
    print(f"Found {len(features)} regions in GeoJSON. Importing to Database...")

    for feature in features:
        props = feature.get("properties", {})
        nuts_id = props.get("NUTS_ID")
        name = props.get("NAME_LATN") or props.get("NUTS_NAME") or nuts_id
        
        if not nuts_id:
            continue
            
        geometry = feature.get("geometry")
        if not geometry:
            continue
            
        coords = geometry.get("coordinates")
        if not coords:
            continue
            
        try:
            # Robust recursive flatten for any geometry nesting depth
            def flatten_coords(coords):
                lons, lats = [], []
                if isinstance(coords[0], (int, float)):
                    return [coords[0]], [coords[1]]
                for item in coords:
                    lo, la = flatten_coords(item)
                    lons.extend(lo)
                    lats.extend(la)
                return lons, lats
            
            lons, lats = flatten_coords(coords)
            if not lons:
                continue
            
            avg_lat = sum(lats) / len(lats)
            avg_lon = sum(lons) / len(lons)
        except Exception as e:
            print(f"Failed to parse geometry for {nuts_id}: {e}")
            continue

        existing = db.query(Location).filter(Location.nuts_id == nuts_id).first()
        if not existing:
            loc = Location(
                nuts_id=nuts_id,
                name=name,
                level=3,
                latitude=avg_lat,
                longitude=avg_lon
            )
            db.add(loc)
            count += 1
            
            # Commit every 500 regions
            if count % 500 == 0:
                db.commit()

    db.commit()
    db.close()
    print(f"Done! Imported {count} new European regions into the database.")

if __name__ == "__main__":
    import_nuts3()
