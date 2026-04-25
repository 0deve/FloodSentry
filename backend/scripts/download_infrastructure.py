"""Download critical infrastructure data from OpenStreetMap Overpass API.

Fetches hospitals and schools for Romania (initial focus area) and saves
as GeoJSON for impact-based flood risk analysis.
"""

import json
import urllib.request
import urllib.parse

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

QUERY = """
[out:json][timeout:60];
area["ISO3166-1"="RO"][admin_level=2]->.searchArea;
(
  nwr["amenity"="hospital"](area.searchArea);
  nwr["amenity"="school"](area.searchArea);
);
out center;
"""


def overpass_to_geojson(elements):
    """Convert Overpass API elements to GeoJSON FeatureCollection."""
    features = []
    for el in elements:
        if el["type"] == "node":
            lon, lat = el["lon"], el["lat"]
        elif "center" in el:
            lon, lat = el["center"]["lon"], el["center"]["lat"]
        else:
            continue

        tags = el.get("tags", {})
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat],
            },
            "properties": {
                "osm_id": el["id"],
                "osm_type": el["type"],
                "name": tags.get("name", "Unknown"),
                "amenity": tags.get("amenity", "unknown"),
                "type": tags.get("amenity", "unknown"),
            },
        }
        features.append(feature)

    return {"type": "FeatureCollection", "features": features}


def main():
    print("Fetching critical infrastructure from OpenStreetMap...")
    data = urllib.parse.urlencode({"data": QUERY}).encode("utf-8")
    req = urllib.request.Request(OVERPASS_URL, data=data)
    req.add_header("User-Agent", "FloodSentry/1.0 (CASSINI Hackathon)")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())

    elements = result.get("elements", [])
    print(f"Found {len(elements)} elements")

    geojson = overpass_to_geojson(elements)
    hospitals = sum(1 for f in geojson["features"] if f["properties"]["amenity"] == "hospital")
    schools = sum(1 for f in geojson["features"] if f["properties"]["amenity"] == "school")
    print(f"  Hospitals: {hospitals}")
    print(f"  Schools: {schools}")

    output_path = "data/critical_infrastructure.geojson"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False)

    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
