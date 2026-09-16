# LECO-Open-DSS

OpenDSS distribution network modeling, visualization, and load profile simulation tool for LECO (Lanka Electricity Company) 11kV / 400V primary substations and distributors.

## 📌 Project Overview
This repository contains network data, load profiles, solar report datasets, and visualization interfaces for LECO's 11kV to 400V distribution transformers:
- **Network Topologies**: KML/KMZ and Excel network data for transformers (e.g., `BZ0109`, `BZ0030`, `AZ0012`, etc.) defining pole connections, conductors, and customers.
- **Load Profiles**: 15-minute time-series recordings for distribution transformers and customer meters.
- **Solar Reports**: Mapped rooftop PV solar inverter capacities per pole.
- **GridVision Visualizers**:
  - Standalone HTML/Leaflet map visualizer (`GridVision.html`) with a 15-minute time slider for voltage regulation monitoring.
  - Python FastAPI engine + OpenDSS simulation dashboard (`app.py`, `opendss_engine.py`).

## 🚀 Quick Start (Python Web UI)
1. Navigate to `extracted_GridVision/package_windows/`
2. Run `1_START_HERE.bat` or launch via Python:
   ```bash
   pip install -r requirements.txt
   python app.py
   ```
3. Open browser at `http://127.0.0.1:8000`
