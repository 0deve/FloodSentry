# FloodSentry: 3D Hydrological Digital Twin for Europe

> **CASSINI Hackathon — "EU Space for Water" — Challenge #3: Disaster Risk Monitoring**

**FloodSentry** is a pan-European, proactive flood risk monitoring system that transforms raw Copernicus satellite data and Galileo positioning into **impact-based flood forecasts**. Instead of generic weather alerts, FloodSentry tells authorities _exactly which hospital, school, or community_ is at risk — and when.

---

## Key Features

| Feature | Description |
|---------|-------------|
| **3D Digital Twin** | Interactive Deck.gl map with extruded NUTS-2 regions colored by real-time risk scores |
| **ML Hazard Classifier** | XGBoost model trained on Copernicus EMS historical flood events (fluvial, pluvial, snowmelt) |
| **GNN-Lite Risk Propagation** | Graph-based model simulating how flood risk travels downstream through the hydrographic network |
| **Impact-Based Alerts** | Goes beyond "it will rain" — identifies affected population, hospitals, and schools per NUTS-3 region |
| **CAP XML Export** | Auto-generates Common Alerting Protocol XML files, ready for RO-Alert / EU-Alert integration |
| **Hydrologic Simulator** | Time-slider simulation showing how upstream rainfall propagates downstream over 72 hours |
| **Executive PDF Reports** | One-click PDF generation for mayors and emergency services |

---

## EU Space Technologies Used

### Copernicus
- **Sentinel-1** (SAR) — Flood extent mapping through cloud cover
- **Sentinel-2** (Optical/NDWI) — Water body detection and vegetation stress
- **Sentinel-3** (SLSTR/Snow) — Fractional Snow Cover & Snow Water Equivalent for snowmelt risk
- **Copernicus DEM** — 3D terrain model for the Digital Twin visualization
- **Copernicus EMS** — Historical flood activation data as ML training ground truth

### Galileo
- **High-accuracy positioning** — "Locate Me" feature for field teams to identify their NUTS region instantly

### Open-Meteo (Copernicus Climate Data Store)
- **ERA5 Reanalysis** — Temperature, rainfall, soil moisture forecasts feeding the ML model

---

## Architecture

```
┌──────────────────────────────────┐     ┌──────────────────────────────┐
│        Frontend (Vite + TS)      │     │     Backend (FastAPI)         │
│  ┌────────────────────────────┐  │     │  ┌────────────────────────┐  │
│  │   Deck.gl 3D Digital Twin  │◄─┼─API─┼─►│  Impact Analysis API   │  │
│  │   - Extruded NUTS polygons │  │     │  │  - /impact/summary     │  │
│  │   - Infrastructure markers │  │     │  │  - /predictions        │  │
│  │   - Lighting & animations  │  │     │  │  - /alerts/evaluate    │  │
│  └────────────────────────────┘  │     │  └────────────────────────┘  │
│  ┌────────────────────────────┐  │     │  ┌────────────────────────┐  │
│  │  Sidebar Impact Analysis   │  │     │  │  ML Engine             │  │
│  │  - Region cards            │  │     │  │  - XGBoost Classifier  │  │
│  │  - Narrative details       │  │     │  │  - GNN-Lite Propagator │  │
│  │  - CAP XML / PDF export    │  │     │  │  - Copernicus Pipeline │  │
│  └────────────────────────────┘  │     │  └────────────────────────┘  │
│  ┌────────────────────────────┐  │     │  ┌────────────────────────┐  │
│  │  Hydrologic Simulator      │  │     │  │  SQLite Database       │  │
│  │  - Time-slider playback    │  │     │  │  - Locations (NUTS)    │  │
│  │  - Rainfall control        │  │     │  │  - Infrastructure      │  │
│  └────────────────────────────┘  │     │  │  - Predictions         │  │
└──────────────────────────────────┘     │  │  - Alerts              │  │
                                         │  └────────────────────────┘  │
                                         └──────────────────────────────┘
```

---

## What Makes FloodSentry Different from EFAS?

> **EFAS gives a general alert on a river basin. FloodSentry translates that general alert into specific local impact: "Hospital X and School Y in NUTS RO224 will be affected in 4 hours", using a 3D Digital Twin and graph-based risk propagation.**

---

## Quick Start

The easiest way to get FloodSentry running on Windows is using the automated scripts.

### 1. Automated Setup
Run the setup script to check requirements (Python, Node.js), create the virtual environment, install dependencies, and seed the initial database.
```bash
./setup_project.bat
```
*Note: If Python or Node.js are missing, the script will offer to install them via `winget` automatically.*

### 2. Run the Project
Once setup is complete, start both the Backend (FastAPI) and Frontend (Vite) services:
```bash
./run_project.bat
```
- **Digital Twin UI:** http://localhost:5173
- **API Documentation:** http://127.0.0.1:8001/docs

---

## Manual Setup (Advanced)
If you prefer to set up the services manually:

### Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python scripts/seed_db.py
uvicorn app.main:app --reload --port 8001
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

---

## Demo Flow (90 seconds)

| Time | Action | Talking Point |
|------|--------|---------------|
| 0-15s | Open 3D map, rotate camera | "Welcome to FloodSentry — a pan-European 3D Digital Twin built on the NUTS standard and powered by Copernicus." |
| 15-30s | Show colored extruded regions | "Our ML model learns from historical Copernicus EMS flood events. Rivers are modeled as graphs. We know what's coming before it arrives." |
| 30-45s | Click a red zone | "We don't just tell you there's risk. We tell you the IMPACT. Here, 12,000 people and the County Hospital are in danger from rapid snowmelt (Sentinel-3 data)." |
| 45-65s | Play Simulator (Time-Slider) | "This is our spatio-temporal model. Watch how water from upstream increases risk downstream over 12 hours." |
| 65-80s | Click Export Emergency Alert (XML) | "When risk is confirmed, we auto-generate a CAP XML data package, ready for instant broadcast through government cell broadcast systems." |
| 80-90s | Zoom out | "FloodSentry. We go from 'it's raining' to 'evacuate Hospital X in 4 hours'. Thank you." |

---

## TAIKAI Submission Checklist

- [x] **Title:** FloodSentry: 3D Hydrological Digital Twin for Europe
- [x] **EU Space Tech:** Sentinel-1, Sentinel-2, Sentinel-3 (Snow), DEM (3D twin), EMS (Historical truth), Galileo
- [x] **Architecture:** NUTS standard, XGBoost + GNN-lite, Impact-based (hospitals), CAP XML export
- [x] **3D Visualization:** Deck.gl extruded polygons with lighting effects
- [x] **Working Demo:** Backend API + Frontend Digital Twin

---

## Team

Built for the **CASSINI Hackathon "EU Space for Water"** — Challenge #3: Disaster Risk Monitoring.

---

## License

MIT License — Built with using EU Space data.
