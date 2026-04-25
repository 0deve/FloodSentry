import json
with open('frontend/public/nuts_regions.geojson', encoding='utf-8') as f:
    d = json.load(f)
ro = [f['properties']['NUTS_ID'] for f in d['features'] if f['properties'].get('CNTR_CODE') == 'RO']
print(f"Total RO regions in geojson: {len(ro)}")
if len(ro) > 0:
    print(ro[:5])
