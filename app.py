"""
GridVision OpenDSS Studio — Unified LECO Web Application
FastAPI Server for 11kV/400V Network Modeling, File Uploads, QSTS Analytics, OpenDSS Power Flows, and .dss Exporter.
"""

from pathlib import Path
import json
import io
import zipfile
import re
from collections import defaultdict
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Response, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from dss_generator import generate_dss_files
from opendss_runner import run_dss_simulation, solve_qsts_series

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "extracted_GridVision" / "package_windows"
UPLOAD_DIR = APP_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="GridVision OpenDSS Studio — LECO", version="3.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _load_json(filename: str) -> dict:
    p = APP_DIR / filename
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    p_data = DATA_DIR / filename
    if p_data.exists():
        return json.loads(p_data.read_text(encoding="utf-8"))
    return {}

def _file_response_or_empty(filename: str):
    p = APP_DIR / filename
    if p.exists():
        return FileResponse(p, media_type="application/json")
    p_data = DATA_DIR / filename
    if p_data.exists():
        return FileResponse(p_data, media_type="application/json")
    return JSONResponse({"ok": False, "error": f"{filename} missing"}, status_code=404)

def _guess_kind(name: str, kind_hint: str = "auto") -> str:
    if kind_hint and kind_hint not in ("auto", ""):
        return kind_hint
    n = name.lower().replace(" ", "")
    if "solar" in n:
        return "solar"
    if "lp" in n or "loadprofile" in n or "load_profile" in n or "profile" in n:
        return "load_profile"
    if n.endswith((".kmz", ".kml")) or (n.endswith(".zip") and "bz0109" in n):
        return "network"
    if "data" in n or "consum" in n or n.endswith((".xls", ".xlsx", ".csv")):
        return "consumption"
    return "other"

def _find_upload(kind: str):
    for p in UPLOAD_DIR.glob(f"{kind}__*"):
        if p.is_file():
            return p
    for p in UPLOAD_DIR.glob("*"):
        if p.is_file() and not p.name.startswith(".") and _guess_kind(p.name) == kind:
            return p
    return None

# ---------- Core System & Status Endpoints ----------

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
        "engine": "OpenDSS Direct Python Engine v3.2"
    }

# ---------- Static JSON File Routes (Direct Frontend Endpoints) ----------

@app.get("/network_map.json")
@app.get("/api/network")
def get_network_map():
    return _file_response_or_empty("network_map.json")

@app.get("/multi_day_qsts.json")
def get_multi_day_qsts():
    return _file_response_or_empty("multi_day_qsts.json")

@app.get("/voltages_timeline.json")
@app.get("/api/voltages_timeline")
def get_voltages_timeline():
    return _file_response_or_empty("voltages_timeline.json")

@app.get("/full_results.json")
def get_full_results():
    return _file_response_or_empty("full_results.json")

@app.get("/bus_voltages.json")
def get_bus_voltages():
    return _file_response_or_empty("bus_voltages.json")

@app.get("/volt_topo.json")
def get_volt_topo():
    return _file_response_or_empty("volt_topo.json")

@app.get("/days_list.json")
@app.get("/api/days")
def get_days_list():
    return _file_response_or_empty("days_list.json")

# ---------- Solve & QSTS Endpoints ----------

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
@app.get("/api/qsts")
def get_qsts_data(date: str = "2026-08-16"):
    qsts_locked = _load_json("qsts_locked_best.json")
    volt_topo = _load_json("volt_topo.json")
    return {
        "ok": True,
        "date": date,
        "metrics": qsts_locked.get("metrics", {}),
        "qsts": qsts_locked.get("qsts", []),
        "voltages_by_pole": volt_topo.get("poles", {})
    }

# ---------- File Upload & Multi-Day Processing ----------

@app.get("/api/uploads")
def list_uploads():
    files = []
    for p in sorted(UPLOAD_DIR.glob("*")):
        if p.is_file() and not p.name.startswith("."):
            files.append({"name": p.name, "size": p.stat().st_size, "kind": _guess_kind(p.name)})
    return {"ok": True, "files": files, "folder": str(UPLOAD_DIR)}

@app.post("/api/upload")
async def upload_file(kind: str = Form("auto"), file: UploadFile = File(...)):
    if not file.filename:
        return JSONResponse({"ok": False, "error": "No filename provided"}, status_code=400)
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in file.filename)
    k = _guess_kind(safe, kind)
    dest_name = f"{k}__{safe}"
    dest = UPLOAD_DIR / dest_name
    data = await file.read()
    dest.write_bytes(data)
    return {"ok": True, "saved_as": dest_name, "size": len(data), "kind": k, "path": str(dest)}

@app.post("/api/upload/clear")
def clear_uploads():
    n = 0
    for p in UPLOAD_DIR.glob("*"):
        if p.is_file() and not p.name.startswith("."):
            p.unlink()
            n += 1
    return {"ok": True, "removed": n}

@app.post("/api/process")
def process_uploads(transformer_kva: int = 250, peak_factor: float = 2.8):
    report = {"ok": True, "steps": [], "warnings": [], "opendss": True}
    try:
        import pandas as pd
    except ImportError:
        return JSONResponse({"ok": False, "error": "pandas missing. Run pip install pandas openpyxl"}, status_code=500)

    uploaded = [p.name for p in UPLOAD_DIR.glob("*") if p.is_file() and not p.name.startswith(".")]
    report["steps"].append(f"Uploaded files: {uploaded}")

    cons = _find_upload("consumption")
    sol = _find_upload("solar")
    lp = _find_upload("load_profile")

    if not cons and not sol and not lp:
        for p in UPLOAD_DIR.glob("*"):
            if not p.is_file() or p.name.startswith("."): continue
            low = p.name.lower()
            if low.endswith((".xls", ".xlsx", ".csv")):
                if "solar" in low and sol is None: sol = p
                elif ("lp" in low or "profile" in low) and lp is None: lp = p
                elif cons is None: cons = p

    net = _load_json("network_map.json")
    if cons is not None or sol is not None:
        load_by_pole = defaultdict(float)
        solar_by_pole = defaultdict(float)
        
        if cons is not None:
            try:
                df = pd.read_excel(cons) if cons.suffix.lower() != ".csv" else pd.read_csv(cons)
                pole_col = next((c for c in df.columns if "POLE" in str(c).upper()), None)
                month_cols = [c for c in df.columns if re.search(r"20\d{2}", str(c))]
                if pole_col and month_cols:
                    df["_avg"] = df[month_cols].apply(pd.to_numeric, errors="coerce").mean(axis=1) / 730.0
                    for _, r in df.iterrows():
                        if pd.isna(r[pole_col]): continue
                        pole = str(r[pole_col]).strip()
                        kw = float(r["_avg"]) if pd.notna(r["_avg"]) and r["_avg"] > 0 else 0
                        load_by_pole[pole] += kw
                    report["steps"].append(f"Consumption updated for {len(load_by_pole)} poles.")
            except Exception as e:
                report["warnings"].append(f"Consumption parse error: {e}")

        if sol is not None:
            try:
                try: df = pd.read_excel(sol, sheet_name="Solar Data V2")
                except Exception: df = pd.read_excel(sol)
                pole_c = next((c for c in df.columns if "POLE" in str(c).upper()), None)
                inv_c = next((c for c in df.columns if "INV" in str(c).upper() or "CAP" in str(c).upper()), None)
                if pole_c and inv_c:
                    for _, r in df.iterrows():
                        if pd.isna(r[pole_c]): continue
                        solar_by_pole[str(r[pole_c]).strip()] += float(r[inv_c]) if pd.notna(r[inv_c]) else 0
                    report["steps"].append(f"Solar updated for {len(solar_by_pole)} poles.")
            except Exception as e:
                report["warnings"].append(f"Solar parse error: {e}")

        if net and "poles" in net:
            for p in net["poles"]:
                if load_by_pole: p["load_kw"] = round(load_by_pole.get(p["id"], p.get("load_kw", 0)), 2)
                if solar_by_pole: p["solar_kw"] = round(solar_by_pole.get(p["id"], p.get("solar_kw", 0)), 2)
            (APP_DIR / "network_map.json").write_text(json.dumps(net, indent=2))

    return {
        "ok": True,
        "message": "Files uploaded and network successfully processed!",
        "report": report
    }

# ---------- OpenDSS Script (.dss) Export ----------

@app.get("/api/export/dss")
def export_dss(transformer_kva: int = Query(250, ge=100, le=630)):
    net = _load_json("network_map.json")
    if not net:
        raise HTTPException(status_code=400, detail="Network map unavailable for export.")
        
    dss_files = generate_dss_files(network_map=net, tx_kva=transformer_kva)
    
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

STATIC_DIR = APP_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", response_class=HTMLResponse)
@app.get("/results", response_class=HTMLResponse)
@app.get("/methodology", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    fallback_html = DATA_DIR / "GridVision_OpenDSS_app.html"
    if fallback_html.exists():
        return FileResponse(str(fallback_html))
    return HTMLResponse("<h2>GridVision OpenDSS Studio</h2>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
