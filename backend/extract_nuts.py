import json, sys, io
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

data = json.load(open("../frontend/public/nuts_regions.geojson", "r", encoding="utf-8"))
by_country = defaultdict(list)

for f in data.get("features", []):
    p = f["properties"]
    nid = p.get("NUTS_ID", "")
    name = p.get("NUTS_NAME", p.get("NAME_LATN", ""))
    cc = nid[:2]
    by_country[cc].append({"id": nid, "name": name})

# Print key flood-prone regions per country
targets = {
    "DE": ["DE111", "DE212", "DE300", "DE600", "DED21", "DEA23", "DE712", "DEA11"],
    "NL": ["NL310", "NL332", "NL226", "NL341"],
    "BE": ["BE100", "BE332", "BE334"],
    "FR": ["FR101", "FRK26", "FRJ21", "FRB01", "FRL01"],
    "IT": ["ITC4C", "ITH31", "ITI14", "ITF33", "ITG17"],
    "ES": ["ES243", "ES511", "ES618", "ES300"],
    "AT": ["AT130", "AT121", "AT311"],
    "HU": ["HU110", "HU321", "HU311"],
    "PL": ["PL911", "PL514", "PL432"],
    "CZ": ["CZ010", "CZ072", "CZ064"],
    "SK": ["SK010", "SK023"],
    "BG": ["BG311", "BG321", "BG411"],
    "HR": ["HR041", "HR042"],
    "RS": ["RS110", "RS121"],
    "EL": ["EL611", "EL431", "EL301"],
    "PT": ["PT170", "PT111"],
    "SE": ["SE110", "SE231"],
    "DK": ["DK011", "DK031"],
    "NO": ["NO081", "NO011"],
    "FI": ["FI1B1", "FI197"],
    "LV": ["LV006", "LV003"],
    "LT": ["LT011", "LT023"],
    "EE": ["EE001", "EE004"],
    "SI": ["SI041", "SI031"],
    "IE": ["IE061", "IE051"],
    "CH": ["CH011", "CH031"],
}

# Check which target IDs actually exist in the GeoJSON
all_ids = {f["properties"].get("NUTS_ID","") for f in data.get("features",[])}

for cc in sorted(targets.keys()):
    items = by_country.get(cc, [])
    print(f"\n{cc} ({len(items)} total):")
    for tid in targets[cc]:
        exists = tid in all_ids
        matching = next((i for i in items if i["id"] == tid), None)
        name = matching["name"] if matching else "NOT FOUND"
        print(f"  {'OK' if exists else 'XX'} {tid}: {name}")
    # Show first 3 actual IDs for reference
    print(f"  Available: {', '.join(i['id'] for i in items[:6])}")
