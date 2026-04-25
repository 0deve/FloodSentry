"""CAP XML Generator — Common Alerting Protocol (RO-Alert compatible).

Generates CAP 1.2 XML documents from Alert records for integration
with RO-Alert (Cell Broadcast) and other government alert systems.

Reference: http://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2.html
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from xml.dom import minidom

from app.models.alert import Alert


# ── CAP Constants ───────────────────────────────────────────────
CAP_NAMESPACE = "urn:oasis:names:tc:emergency:cap:1.2"
SENDER = "floodsentry@igsu.ro"
STATUS = "Actual"
MSG_TYPE = "Alert"
SCOPE = "Public"
CATEGORY = "Met"
EVENT = "Severe Flood Warning"
LANGUAGE = "ro-RO"

# Map internal levels → CAP severity + urgency
SEVERITY_MAP = {
    "emergency": ("Extreme", "Immediate"),
    "critical": ("Severe", "Expected"),
    "warning": ("Moderate", "Future"),
    "info": ("Minor", "Past"),
}

# NUTS region → approximate polygon centroids (for demo)
# In production this would come from a GeoJSON database
REGION_POLYGONS = {
    "RO224": "45.43,28.00 45.55,28.10 45.50,28.25 45.40,28.15 45.43,28.00",
    "RO226": "45.30,27.80 45.42,27.90 45.38,28.05 45.28,27.95 45.30,27.80",
    "RO216": "46.50,27.70 46.62,27.80 46.58,27.95 46.48,27.85 46.50,27.70",
    "RO225": "45.25,27.40 45.37,27.50 45.33,27.65 45.23,27.55 45.25,27.40",
    "RO211": "46.90,26.30 47.02,26.40 46.98,26.55 46.88,26.45 46.90,26.30",
    "HU333": "46.25,20.15 46.37,20.25 46.33,20.40 46.23,20.30 46.25,20.15",
    "BG334": "43.85,25.95 43.97,26.05 43.93,26.20 43.83,26.10 43.85,25.95",
}

# NUTS region → area description
REGION_AREA_DESC = {
    "RO224": "Județul Galați (NUTS RO224)",
    "RO226": "Județul Vrancea (NUTS RO226)",
    "RO216": "Județul Vaslui (NUTS RO216)",
    "RO225": "Județul Buzău (NUTS RO225)",
    "RO211": "Județul Bacău (NUTS RO211)",
    "HU333": "Csongrád-Csanád megye (NUTS HU333)",
    "BG334": "Oblast Pleven (NUTS BG334)",
}


def generate_cap_xml(alert: Alert) -> str:
    """Generate a CAP 1.2 XML document from an Alert record.

    Returns a pretty-printed XML string ready for download.
    """
    now = datetime.now(timezone.utc)
    sent_time = alert.created_at or now

    # Root <alert> element
    root = ET.Element("alert")
    root.set("xmlns", CAP_NAMESPACE)

    # Header elements
    _add_text(root, "identifier", f"FS-{now.strftime('%Y')}-{alert.id:04d}")
    _add_text(root, "sender", SENDER)
    _add_text(root, "sent", _cap_datetime(sent_time))
    _add_text(root, "status", STATUS)
    _add_text(root, "msgType", MSG_TYPE)
    _add_text(root, "scope", SCOPE)

    # <info> block
    info = ET.SubElement(root, "info")
    _add_text(info, "language", LANGUAGE)
    _add_text(info, "category", CATEGORY)
    _add_text(info, "event", EVENT)
    _add_text(info, "responseType", "Evacuate" if alert.level == "emergency" else "Prepare")

    severity, urgency = SEVERITY_MAP.get(alert.level, ("Unknown", "Unknown"))
    _add_text(info, "urgency", urgency)
    _add_text(info, "severity", severity)
    _add_text(info, "certainty", "Observed" if alert.level in ("emergency", "critical") else "Likely")

    # Event code (NUTS-based)
    event_code = ET.SubElement(info, "eventCode")
    _add_text(event_code, "valueName", "NUTS_ID")
    _add_text(event_code, "value", alert.nuts_id)

    # Timestamps
    _add_text(info, "effective", _cap_datetime(sent_time))
    _add_text(info, "expires", _cap_datetime(sent_time.replace(hour=sent_time.hour + 12 if sent_time.hour < 12 else sent_time.hour - 12)))

    # Sender name
    _add_text(info, "senderName", "FloodSentry — EU Flood Risk Monitoring System")

    # Headline & description
    _add_text(info, "headline", alert.title or f"Flood Alert — {alert.nuts_id}")
    _add_text(info, "description", alert.description or "Risc de inundație detectat în regiunea monitorizată.")
    _add_text(info, "instruction", _get_instructions(alert.level))

    # Web link
    _add_text(info, "web", "https://floodsentry.eu/alerts")

    # Contact
    _add_text(info, "contact", "IGSU — Inspectoratul General pentru Situații de Urgență")

    # <area> block
    area = ET.SubElement(info, "area")
    area_desc = REGION_AREA_DESC.get(alert.nuts_id, f"NUTS Region {alert.nuts_id}")
    _add_text(area, "areaDesc", area_desc)

    polygon = REGION_POLYGONS.get(alert.nuts_id)
    if polygon:
        _add_text(area, "polygon", polygon)

    # Geocode
    geocode = ET.SubElement(area, "geocode")
    _add_text(geocode, "valueName", "NUTS")
    _add_text(geocode, "value", alert.nuts_id)

    # Pretty-print
    rough_string = ET.tostring(root, encoding="unicode", xml_declaration=False)
    xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
    pretty = minidom.parseString(rough_string).toprettyxml(indent="  ")
    # Remove the default xml declaration from minidom and use our own
    lines = pretty.split("\n")
    if lines[0].startswith("<?xml"):
        lines = lines[1:]
    return xml_declaration + "\n".join(lines)


def _add_text(parent: ET.Element, tag: str, text: str) -> ET.Element:
    """Add a child element with text content."""
    el = ET.SubElement(parent, tag)
    el.text = text
    return el


def _cap_datetime(dt: datetime) -> str:
    """Format datetime as CAP-compliant ISO 8601 with timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def _get_instructions(level: str) -> str:
    """Get evacuation/preparedness instructions based on severity."""
    instructions = {
        "emergency": (
            "EVACUARE IMEDIATĂ: Părăsiți imediat zona luncii inundabile. "
            "Urmați indicațiile autorităților locale. Evitați traversarea "
            "cursurilor de apă. Contactați 112 în caz de urgență."
        ),
        "critical": (
            "PREGĂTIRE EVACUARE: Fiți pregătiți să evacuați zona în "
            "următoarele ore. Asigurați-vă că aveți un plan de evacuare. "
            "Monitorizați comunicatele oficiale."
        ),
        "warning": (
            "ATENȚIE: Risc moderat de inundație. Evitați zonele joase și "
            "albiile râurilor. Urmăriți evoluția situației meteorologice."
        ),
        "info": (
            "INFORMARE: Risc scăzut de inundație. Mențineți vigilența și "
            "urmăriți buletinele meteorologice."
        ),
    }
    return instructions.get(level, instructions["info"])
