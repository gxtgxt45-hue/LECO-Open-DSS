"""
GridVision OpenDSS Studio — Unified LECO Web Application
FastAPI Server for 11kV/400V Network Modeling, OpenDSS Power Flows, and .dss Exporter.
"""

from pathlib import Path
import json
import io
import zipfile
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from dss_generator import generate_dss_files
from opendss_runner import run_dss_simulation, solve_qsts_series

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "extracted_GridVision" / "package_windows"

app = FastAPI(title="GridVision OpenDSS Studio — LECO", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helper function to load cached JSON files
def _load_json(filename: str) -> dict:
    p = DATA_DIR / filename
    if not p.exists():
        p_root = APP_DIR / filename
        if p_root.exists():
            return json.loads(p_root.read_text(encoding="utf-8"))
        return {}
    return json.loads(p.read_text(encoding="utf-8"))

@app.get("/api/health")
def health():
    return {"status": "ok", "system": "LECO GridVision OpenDSS Studio", "transformer": "BZ0109"}

@app.get("/api/status")
def status():
    net = _load_json("network_map.json")
    poles = net.get("poles", [])
    total_load = sum(float(p.get("load_kw") or 0) for p in poles)
    total_solar = sum(float(p.get("solar_kw") or 0) for p in poles)
    
    return {
        "ok": True,
        "transformer_id": "BZ0109",
        "primary_voltage_kv": 11.0,
        "secondary_voltage_v": 400.0,
        "transformer_kva_default": 250,
        "n_poles": len(poles),
        "n_lines": len(net.get("lines", [])),
        "total_load_kw": round(total_load, 2),
        "total_solar_kw": round(total_solar, 2),
        "has_qsts": True,
        "engine": "OpenDSS Direct Python Engine v3.0"
    }

@app.get("/api/network")
def get_network():
    net = _load_json("network_map.json")
    if not net:
        raise HTTPException(status_code=444, detail="Network map data not found.")
    return net

@app.get("/api/days")
def get_days():
    days = _load_json("days_list.json")
    if not days:
        # Fallback days list
        return {
            "ok": True,
            "n_days": 15,
            "days": [{"date": f"2026-08-{d:02d}", "day_type": "weekday"} for d in range(11, 26)],
            "locked_day": "2026-08-16"
        }
    return days

@app.get("/api/solve/snapshot")
def solve_snapshot(mode: str = Query("noon", enum=["peak", "noon"]), transformer_kva: int = 250):
    net = _load_json("network_map.json")
    poles = net.get("poles", [])
    
    is_noon = (mode == "noon")
    time_label = "12:15 (Solar Noon)" if is_noon else "19:00 (Peak Load)"
    
    pole_results = []
    v_min_all, v_max_all = 300.0, 0.0
    
    for p in poles:
        v_data = p.get("V_noon" if is_noon else "V_peak", {})
        va = v_data.get("Va", 230.0)
        vb = v_data.get("Vb", 230.0)
        vc = v_data.get("Vc", 230.0)
        
        v_min_all = min(v_min_all, va, vb, vc)
        v_max_all = max(v_max_all, va, vb, vc)
        
        pole_results.append({
            "id": p["id"],
            "lat": p.get("lat"),
            "lon": p.get("lon"),
            "feeder": p.get("feeder"),
            "Va": va,
            "Vb": vb,
            "Vc": vc,
            "unbal_pct": v_data.get("unbal_pct", 0.0),
            "load_kw": p.get("load_kw", 0),
            "solar_kw": p.get("solar_kw", 0),
        })
        
    return {
        "ok": True,
        "mode": mode,
        "time_label": time_label,
        "transformer_kva": transformer_kva,
        "v_min": round(v_min_all, 1),
        "v_max": round(v_max_all, 1),
        "poles": pole_results
    }

@app.get("/api/solve/qsts")
def get_qsts_data(date: str = "2026-08-16"):
    # Load multi-day QSTS dataset or locked best
    qsts_locked = _load_json("qsts_locked_best.json")
    volt_topo = _load_json("volt_topo.json")
    
    return {
        "ok": True,
        "date": date,
        "metrics": qsts_locked.get("metrics", {}),
        "qsts": qsts_locked.get("qsts", []),
        "voltages_by_pole": volt_topo.get("poles", {})
    }

@app.get("/api/export/dss")
def export_dss(transformer_kva: int = Query(250, ge=100, le=630)):
    """
    Generates and returns clean OpenDSS (.dss) files packaged as a ZIP archive for LECO engineers.
    """
    net = _load_json("network_map.json")
    if not net:
        raise HTTPException(status_code=400, detail="Network map unavailable for export.")
        
    dss_files = generate_dss_files(network_map=net, tx_kva=transformer_kva)
    
    # Create ZIP buffer in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, content in dss_files.items():
            zf.writestr(f"LECO_BZ0109_OpenDSS/{fname}", content)
            
    zip_buffer.seek(0)
    
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=LECO_BZ0109_OpenDSS_{transformer_kva}kVA.zip"}
    )

# Mount static files directory if static folder exists
STATIC_DIR = APP_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", response_class=HTMLResponse)
def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    # Fallback to extracted app HTML if static directory not created yet
    fallback_html = DATA_DIR / "GridVision_OpenDSS_app.html"
    if fallback_html.exists():
        return FileResponse(str(fallback_html))
    return HTMLResponse("<h2>GridVision OpenDSS Studio</h2><p>Frontend loading...</p>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
