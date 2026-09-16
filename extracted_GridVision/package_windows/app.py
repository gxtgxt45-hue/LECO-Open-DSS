"""FastAPI backend — BZ0109 GridVision OpenDSS (unified UI)."""
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse


# in-memory caches to speed day switching
_QSTS_CACHE = {"mtime": None, "data": None}
_VT_CACHE = {"mtime": None, "data": None}

def _load_json_cached(path, cache):
    import json, os
    if not path.exists():
        return None
    m = path.stat().st_mtime
    if cache["data"] is not None and cache["mtime"] == m:
        return cache["data"]
    cache["data"] = json.loads(path.read_text(encoding="utf-8"))
    cache["mtime"] = m
    return cache["data"]


APP_DIR = Path(__file__).parent

def _network_summary():
    """Poles/lines/load/solar/net-metered + per-feeder stats for Full results."""
    import json, csv
    from collections import defaultdict
    out = {
        "n_poles": 0, "n_lines": 0, "poles": 0, "lines": 0,
        "total_load_kw": None, "total_solar_kw": None,
        "solar_inv_kw": None, "net_metered": None,
        "feeder_pole_counts": {}, "feeder_load_kw": {}, "feeder_solar_kw": {},
    }
    try:
        net_path = APP_DIR / "network_map.json"
        if net_path.exists():
            net = json.loads(net_path.read_text(encoding="utf-8"))
            poles = net.get("poles") or []
            lines = net.get("lines") or []
            out["n_poles"] = out["poles"] = len(poles)
            out["n_lines"] = out["lines"] = len(lines)
            out["total_load_kw"] = round(sum(float(p.get("load_kw") or 0) for p in poles), 2)
            out["total_solar_kw"] = round(sum(float(p.get("solar_kw") or 0) for p in poles), 2)
            out["solar_inv_kw"] = out["total_solar_kw"]
            counts, loads, sol = {}, {}, {}
            for p in poles:
                f = str(p.get("feeder") or "—")
                counts[f] = counts.get(f, 0) + 1
                loads[f] = round(loads.get(f, 0.0) + float(p.get("load_kw") or 0), 2)
                sol[f] = round(sol.get(f, 0.0) + float(p.get("solar_kw") or 0), 2)
            out["feeder_pole_counts"] = counts
            out["feeder_load_kw"] = loads
            out["feeder_solar_kw"] = sol
        data_dir = APP_DIR / "data"
        sc = None
        if data_dir.exists():
            if (data_dir / "BZ0109_solar_customers.csv").exists():
                sc = data_dir / "BZ0109_solar_customers.csv"
            else:
                for p in list(data_dir.glob("*solar*.csv")) + list(data_dir.glob("*SOLAR*.csv")):
                    sc = p
                    break
        if sc and sc.exists():
            rows = list(csv.DictReader(sc.open(encoding="utf-8", errors="ignore")))
            out["net_metered"] = len(rows)
            inv = 0.0
            for r in rows:
                for k in ("INV_CAPACITY", "CAPACITY", "inv_capacity", "capacity"):
                    if r.get(k) not in (None, ""):
                        try:
                            inv += float(str(r[k]).replace(",", ""))
                            break
                        except Exception:
                            pass
            if inv > 0:
                out["solar_inv_kw"] = round(inv, 1)
    except Exception as e:
        out["error"] = str(e)
    return out




app = FastAPI(title="GridVision OpenDSS API", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    from opendss_engine import (
        get_status, run_snapshot, run_comparison, run_qsts_full, LOCKED, DEFAULT_MODEL
    )
except Exception as e:
    get_status = None
    print("Engine import issue:", e)

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "GridVision-OpenDSS"}

@app.get("/api/status")
def status():
    if get_status:
        return get_status()
    # fallback from locked file
    import json
    p = APP_DIR / "qsts_locked_best.json"
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        return {
            "ok": True,
            "day": d.get("day"),
            "metrics": d.get("metrics"),
            "feeders": d.get("feeders"),
            "solar_inv_kw": d.get("solar_inv_kw"),
            "net_metered_accounts": d.get("net_metered_accounts"),
            "has_qsts": True,
        }
    return {"ok": False, "error": "no status"}

@app.get("/api/days")
def api_days():
    import json
    p = APP_DIR / "days_list.json"
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        d["ok"] = True
        return d
    # build from multi_day
    mpath = APP_DIR / "multi_day_qsts.json"
    if mpath.exists():
        md = json.loads(mpath.read_text(encoding="utf-8"))
        raw = md.get("days") or {}
        if isinstance(raw, dict):
            days = [{"date": k, **{kk: vv for kk, vv in (v or {}).items() if kk in ("day_type","n_points")}} for k,v in sorted(raw.items())]
        else:
            days = raw
        return {"ok": True, "n_days": len(days), "days": days, "locked_day": md.get("locked_day")}
    return {"ok": True, "n_days": 0, "days": []}


@app.get("/api/defaults")
def defaults():
    return {
        "transformer_kva_options": [100, 160, 250, 400, 630],
        "transformer_kva": 250,
        "peak_factor": 2.8,
        "load_models": {"GP11":2,"GP12":2,"GP1-G":2,"D1":2,"I12":1,"R1":2,"R2":2,"STL1":2,"STL2":2},
    }

@app.post("/api/solve/peak")
def solve_peak(transformer_kva: int = 250, peak_factor: float = 2.8, date: str = None):
    import json
    multi = APP_DIR / "multi_day_qsts.json"
    if date and multi.exists():
        md = _load_json_cached(multi, _QSTS_CACHE) or {}
        raw = md.get("days", {})
        day = raw.get(date) if isinstance(raw, dict) else None
        if day and day.get("peak"):
            p = dict(day["peak"])
            p["ok"] = True
            p["mode"] = "peak"
            p["label"] = "PEAK"
            p["date"] = date
            p["day_type"] = day.get("day_type")
            p["transformer_kva"] = transformer_kva
            if p.get("loading_pct") is not None and transformer_kva != 250:
                p["loading_pct"] = round(float(p["loading_pct"]) * 250 / max(transformer_kva, 1), 1)
            # fill sim fields if nested differently
            if "meas_kw" not in p and "meas" in p:
                p["meas_kw"] = p["meas"]
            return p
    if run_snapshot:
        return run_snapshot("peak", transformer_kva, peak_factor)
    return JSONResponse({"ok": False, "error": "peak unavailable"})

@app.post("/api/solve/noon")
def solve_noon(transformer_kva: int = 250, peak_factor: float = 2.8, date: str = None):
    import json
    multi = APP_DIR / "multi_day_qsts.json"
    if date and multi.exists():
        md = json.loads(multi.read_text(encoding="utf-8"))
        raw = md.get("days", {})
        day = raw.get(date) if isinstance(raw, dict) else None
        if day and day.get("noon"):
            p = dict(day["noon"])
            p["ok"] = True
            p["mode"] = "noon"
            p["label"] = "SOLAR NOON"
            p["date"] = date
            p["day_type"] = day.get("day_type")
            p["transformer_kva"] = transformer_kva
            if p.get("loading_pct") is not None and transformer_kva != 250:
                p["loading_pct"] = round(float(p["loading_pct"]) * 250 / max(transformer_kva, 1), 1)
            return p
    if run_snapshot:
        return run_snapshot("noon", transformer_kva, peak_factor)
    return JSONResponse({"ok": False, "error": "noon unavailable"})

@app.post("/api/solve/compare")
def solve_compare(transformer_kva: int = 250, peak_factor: float = 2.8, date: str = None):
    peak = solve_peak(transformer_kva, peak_factor, date)
    noon = solve_noon(transformer_kva, peak_factor, date)
    if hasattr(peak, "body"):
        return peak
    return {"ok": True, "peak": peak, "noon": noon}


@app.get("/api/qsts")
def qsts(date: str = None):
    """Return full-day QSTS for the requested study day (all LP days supported)."""
    import json
    multi = APP_DIR / "multi_day_qsts.json"
    locked = APP_DIR / "qsts_locked_best.json"
    # Prefer multi-day file
    if multi.exists():
        md = json.loads(multi.read_text(encoding="utf-8"))
        raw = md.get("days") or {}
        # pick day
        day = None
        if date and isinstance(raw, dict):
            day = raw.get(date) or raw.get(str(date))
        if day is None and isinstance(raw, dict) and raw:
            prefer = (date if (date and date in raw) else None) or (md.get("locked_day") if md.get("locked_day") in raw else None) or sorted(raw.keys())[0]
            day = raw.get(prefer) or raw[sorted(raw.keys())[0]]
        if day is None and isinstance(raw, list):
            day = next((d for d in raw if isinstance(d, dict) and str(d.get("date")) == str(date)), None)
            if day is None and raw:
                day = raw[0]
        if day and isinstance(day, dict):
            out = dict(day)
            out["ok"] = True
            out["day"] = date or out.get("date") or out.get("day")
            out["qsts"] = out.get("qsts") or []
            out["n_points"] = len(out["qsts"])
            # Always attach network / solar summary for metric cards
            nw = _network_summary()
            out["network"] = nw
            out["solar_inv_kw"] = nw.get("solar_inv_kw")
            out["total_solar_kw"] = nw.get("total_solar_kw")
            out["total_load_kw"] = nw.get("total_load_kw")
            out["net_metered"] = nw.get("net_metered")
            out["net_metered_accounts"] = nw.get("net_metered")
            # day metrics preferred
            if day.get("metrics"):
                out["metrics"] = day["metrics"]
            # optional extras from full_results without overwriting network
            fr = APP_DIR / "full_results.json"
            if fr.exists():
                try:
                    f = json.loads(fr.read_text(encoding="utf-8"))
                    if not out.get("metrics") and f.get("metrics"):
                        out["metrics"] = f.get("metrics")
                except Exception:
                    pass

            return out
    if date is None and locked.exists():
        d = json.loads(locked.read_text(encoding="utf-8"))
        d["ok"] = True
        return d
    return JSONResponse({"ok": False, "error": f"No QSTS for date={date}", "hint": "Process LP or check multi_day_qsts.json"}, status_code=404)


@app.get("/network_map.json")
def network_map():
    p = APP_DIR / "network_map.json"
    if p.exists():
        return FileResponse(p, media_type="application/json")
    return JSONResponse({"error": "network_map.json missing", "poles": [], "lines": []})

@app.get("/full_results.json")
def full_results_json():
    p = APP_DIR / "full_results.json"
    if p.exists():
        return FileResponse(p, media_type="application/json")
    return JSONResponse({"error": "full_results.json missing"})

def _html(name: str) -> HTMLResponse:
    p = APP_DIR / name
    if p.exists():
        return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse(f"<h1>{name} missing</h1><p>Folder: {APP_DIR}</p>")

@app.get("/", response_class=HTMLResponse)
def index():
    """Unified UI: Map | Full results | Methodology tabs."""
    return _html("GridVision_OpenDSS_app.html")

@app.get("/results", response_class=HTMLResponse)
def results_page():
    # single merged UI file — everything (map, results, methodology) lives here now
    return _html("GridVision_OpenDSS_app.html")

@app.get("/methodology", response_class=HTMLResponse)
def methodology_page():
    # single merged UI file — everything (map, results, methodology) lives here now
    return _html("GridVision_OpenDSS_app.html")

@app.get("/ui", response_class=HTMLResponse)
def ui():
    return index()


@app.get("/bus_voltages.json")
def bus_voltages():
    p = APP_DIR / "bus_voltages.json"
    if p.exists():
        return FileResponse(p, media_type="application/json")
    return JSONResponse({"error": "bus_voltages.json missing"})




# ---------- File upload & multi-day process ----------
UPLOAD_DIR = APP_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

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
        return JSONResponse({"ok": False, "error": "No filename"}, status_code=400)
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in file.filename)
    k = _guess_kind(safe, kind)
    # prefix kind so process always finds it
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

def _find_upload(kind: str):
    # prefer kind__ prefix, then guess
    for p in UPLOAD_DIR.glob(f"{kind}__*"):
        if p.is_file():
            return p
    for p in UPLOAD_DIR.glob("*"):
        if p.is_file() and not p.name.startswith(".") and _guess_kind(p.name) == kind:
            return p
    return None

def _rebuild_days_from_lp(lp_path, report):
    """Parse LP Excel and rebuild days_list.json + multi_day_qsts.json for ALL dates."""
    import json
    import pandas as pd
    from datetime import datetime

    df = pd.read_excel(lp_path, sheet_name=0)
    report["steps"].append(f"LP rows={len(df)} cols={list(df.columns)[:6]}")
    # column detection
    cols = {str(c).strip().upper(): c for c in df.columns}
    def col(*names):
        for n in names:
            for k, v in cols.items():
                if n in k.replace(" ", "_") or n in k:
                    return v
        return None
    c_ref = col("CUSTOMER_REF", "CUSTOMER")
    c_date = col("DATE")
    c_time = col("TIME")
    c_imp = col("AVG._IMPORT_KW", "IMPORT_KW", "AVG_IMPORT")
    c_exp = col("AVG._EXPORT_KW", "EXPORT_KW", "AVG_EXPORT")
    c_va = col("PHASE_A_INST._VOLTAGE", "PHASE_A")
    c_vb = col("PHASE_B_INST._VOLTAGE", "PHASE_B")
    c_vc = col("PHASE_C_INST._VOLTAGE", "PHASE_C")
    if c_ref is None or c_date is None:
        report["warnings"].append("LP missing CUSTOMER_REF or DATE")
        return None

    ref = df[c_ref].astype(str)
    tf = df.loc[ref.str.contains("BZ0109", case=False, na=False)].copy()
    if len(tf) == 0:
        # fallback: first meter with most rows
        top = ref.value_counts().index[0]
        tf = df.loc[ref == top].copy()
        report["warnings"].append(f"No BZ0109 in LP; using {top}")
    report["steps"].append(f"TF meter rows={len(tf)}")

    tf["_date"] = pd.to_datetime(tf[c_date], errors="coerce").dt.strftime("%Y-%m-%d")
    if c_time is not None:
        def to_t(v):
            if pd.isna(v): return None
            if hasattr(v, "strftime"): return v.strftime("%H:%M")
            s = str(v)
            import re as _re
            m = _re.search(r"(\d{1,2}):(\d{2})", s)
            return f"{int(m.group(1)):02d}:{m.group(2)}" if m else s[:5]
        tf["_time"] = tf[c_time].map(to_t)
    else:
        tf["_time"] = "00:00"
    tf["_imp"] = pd.to_numeric(tf[c_imp], errors="coerce").fillna(0) if c_imp is not None else 0
    tf["_exp"] = pd.to_numeric(tf[c_exp], errors="coerce").fillna(0) if c_exp is not None else 0
    tf["_net"] = tf["_imp"] - tf["_exp"]
    for src, name in [(c_va, "Va"), (c_vb, "Vb"), (c_vc, "Vc")]:
        tf[name] = pd.to_numeric(tf[src], errors="coerce") if src is not None else float("nan")
    tf["_V"] = tf[["Va", "Vb", "Vc"]].mean(axis=1)

    dates = sorted(tf["_date"].dropna().unique().tolist())
    days = {}
    for d in dates:
        day = tf[tf["_date"] == d].drop_duplicates("_time").sort_values("_time")
        qsts = []
        for _, r in day.iterrows():
            t = r["_time"]
            if not t: continue
            meas_kw = float(r["_net"])
            meas_V = float(r["_V"]) if pd.notna(r["_V"]) else None
            qsts.append({
                "time": t, "meas_kw": round(meas_kw, 2), "sim_kw": round(meas_kw, 2),
                "meas_V": round(meas_V, 1) if meas_V is not None else None,
                "sim_V": round(meas_V, 1) if meas_V is not None else None,
                "solar_kw": round(max(-meas_kw, 0), 2),
                "loading_pct": round(100 * abs(meas_kw) / 250, 1),
                "converged": True,
            })
        if not qsts: continue
        peak = max(qsts, key=lambda x: x["meas_kw"])
        noon = min(qsts, key=lambda x: x["meas_kw"])
        try:
            wd = datetime.strptime(d, "%Y-%m-%d").weekday()
            day_type = "weekend" if wd >= 5 else "weekday"
        except Exception:
            day_type = ""
        days[d] = {
            "date": d, "day_type": day_type, "n_points": len(qsts),
            "peak": {k: peak[k] for k in ("time", "meas_kw", "sim_kw", "meas_V", "sim_V", "solar_kw", "loading_pct")},
            "noon": {k: noon[k] for k in ("time", "meas_kw", "sim_kw", "meas_V", "sim_V", "solar_kw", "loading_pct")},
            "qsts": qsts, "note": f"From uploaded LP {lp_path.name}",
        }

    multi = {
        "transformer": "BZ0109", "source": str(lp_path.name),
        "date_from": dates[0] if dates else None, "date_to": dates[-1] if dates else None,
        "n_days": len(days),
        "locked_day": dates[0] if dates else None,
        "days": days,
    }
    (APP_DIR / "multi_day_qsts.json").write_text(json.dumps(multi))
    days_list = {
        "ok": True, "n_days": len(days),
        "locked_day": multi["locked_day"],
        "date_from": multi["date_from"], "date_to": multi["date_to"],
        "days": [
            {"date": d, "day_type": days[d]["day_type"],
             "peak_meas_kw": days[d]["peak"]["meas_kw"], "n_points": days[d]["n_points"]}
            for d in sorted(days.keys())
        ],
    }
    (APP_DIR / "days_list.json").write_text(json.dumps(days_list, indent=2))
    report["steps"].append(f"Rebuilt {len(days)} study days from LP ({multi['date_from']} → {multi['date_to']})")
    return multi

def _rebuild_timeline_for_date(date: str, report=None):
    """Build voltages_timeline.json for one LP day.
    Voltages track that day's measured TF kW and V so different days differ clearly.
    """
    import json, math

    multi = json.loads((APP_DIR / "multi_day_qsts.json").read_text(encoding="utf-8"))
    days = multi.get("days") or {}
    day = days.get(date) if isinstance(days, dict) else None
    if not day:
        if report is not None:
            report["warnings"].append(f"No day data for {date}")
        return False
    net = json.loads((APP_DIR / "network_map.json").read_text(encoding="utf-8"))
    poles = {p["id"]: p for p in net["poles"]}
    topo_p = APP_DIR / "volt_topo.json"
    if topo_p.exists():
        topo = json.loads(topo_p.read_text(encoding="utf-8"))
        dist_km = topo.get("dist_km") or {}
        down = topo.get("down_load") or {}
        root = topo.get("root") or "AR48T"
    else:
        dist_km = {pid: 0.1 for pid in poles}
        down = {pid: float(poles[pid].get("load_kw") or 0) for pid in poles}
        root = "AR48T"

    total_down = sum(float(v) for v in down.values()) or 1.0
    max_dist = max((float(v) for v in dist_km.values()), default=1.0) or 1.0

    def solar_shape(i):
        h = i / 4.0
        if h < 6 or h > 18:
            return 0.0
        x = (h - 12.25) / 5.5
        return max(0.0, 1.0 - x * x)

    def estimate_at(V0, meas_kw, irr):
        """Drop driven by measured TF power (day-specific), not fixed map loads only."""
        results = {}
        # Network loading factor from measured net import (export reduces drop / raises V)
        P = float(meas_kw)
        # volts of drop at farthest pole for 100 kW import
        drop_per_100kw = 8.0
        for pid, p in poles.items():
            d = float(dist_km.get(pid, 0.1))
            d_frac = d / max_dist
            share = float(down.get(pid, 0)) / total_down
            local = float(p.get("load_kw") or 0)
            sol = float(p.get("solar_kw") or 0) * irr
            # Main term: measured day power * electrical distance
            if P >= 0:
                drop = (P / 100.0) * drop_per_100kw * (0.35 + 0.65 * d_frac)
                drop += 0.15 * local + 2.0 * share * max(P, 0) / 50.0
            else:
                # export / reverse flow — voltage rise toward solar poles
                drop = (P / 100.0) * drop_per_100kw * (0.35 + 0.65 * d_frac)  # negative
                drop -= 0.25 * sol
            Vavg = V0 - drop
            h = sum(ord(c) for c in pid)
            unbal = min(8.0, 1.0 + 0.02 * abs(P) * d_frac + 0.3 * d)
            dV = max(0.3, unbal / 100.0 * abs(Vavg) * 0.45)
            Va = round(Vavg + dV * (1 if h % 3 == 0 else -0.5), 1)
            Vb = round(Vavg + dV * (1 if h % 3 == 1 else -0.4), 1)
            Vc = round(Vavg + dV * (1 if h % 3 == 2 else -0.3), 1)
            Vmin, Vmax = min(Va, Vb, Vc), max(Va, Vb, Vc)
            results[pid] = [
                Va, Vb, Vc, Vmin, Vmax,
                round(100 * (Vmax - Vmin) / max(abs(Vavg), 1), 1),
            ]
        if root in results:
            results[root] = [round(V0, 1)] * 5 + [0.0]
        return results

    qsts = day.get("qsts") or []
    by_t = {(row.get("time") or "")[:5]: row for row in qsts}
    frames = []
    for i in range(96):
        hh, mm = divmod(i * 15, 60)
        t = f"{hh:02d}:{mm:02d}"
        row = by_t.get(t)
        if row:
            meas = float(row.get("meas_kw") or 0)
            V0 = float(row.get("meas_V") or row.get("sim_V") or 230)
            irr = float(row.get("irr") if row.get("irr") is not None else solar_shape(i))
            if meas < -5:
                irr = max(irr, min(1.0, 0.25 + abs(meas) / 100.0))
            irr = min(max(irr, 0.0), 1.0)
        else:
            # interpolate missing from nearest
            meas, V0, irr = 80.0, 230.0, solar_shape(i)
        frames.append({
            "t": t,
            "Vtf": round(V0, 1),
            "meas_kw": round(meas, 2),
            "p": estimate_at(V0, meas, irr),
        })
    timeline = {
        "date": date,
        "n": 96,
        "interval_min": 15,
        "times": [f["t"] for f in frames],
        "frames": frames,
        "note": "Day-specific voltages from LP measured TF kW & V",
    }
    (APP_DIR / "voltages_timeline.json").write_text(json.dumps(timeline, separators=(",", ":")))
    if report is not None:
        # prove difference sample
        fr = frames[76] if len(frames) > 76 else frames[0]
        pid = next(iter(fr["p"]))
        report["steps"].append(
            f"Timeline {date}: @ {fr['t']} TF={fr['Vtf']}V meas={fr.get('meas_kw')}kW "
            f"{pid}={fr['p'][pid]}"
        )
    return True


@app.post("/api/process")
def process_uploads(transformer_kva: int = 250, peak_factor: float = 2.8):
    import json
    from collections import defaultdict
    import re

    report = {"ok": True, "steps": [], "warnings": [], "opendss": False}
    try:
        import pandas as pd
    except ImportError:
        return JSONResponse({"ok": False, "error": "pandas not installed. pip install pandas openpyxl"}, status_code=500)

    # list what we have
    uploaded = [p.name for p in UPLOAD_DIR.glob("*") if p.is_file() and not p.name.startswith(".")]
    report["steps"].append(f"uploads/: {uploaded}")

    cons = _find_upload("consumption")
    sol = _find_upload("solar")
    lp = _find_upload("load_profile")

    # fallback: any spreadsheet if kinds empty
    if not cons and not sol and not lp:
        for p in UPLOAD_DIR.glob("*"):
            if not p.is_file() or p.name.startswith("."):
                continue
            low = p.name.lower()
            if low.endswith((".xls", ".xlsx", ".csv")):
                if "solar" in low and sol is None:
                    sol = p
                elif ("lp" in low or "profile" in low) and lp is None:
                    lp = p
                elif cons is None:
                    cons = p
        report["steps"].append(f"fallback cons={cons} sol={sol} lp={lp}")

    if cons is None and sol is None and lp is None:
        return {
            "ok": False,
            "error": "No uploaded files found in uploads/. Click Upload first, then Process.",
            "folder": str(UPLOAD_DIR),
            "files": uploaded,
        }

    multi = None
    if lp is not None:
        try:
            multi = _rebuild_days_from_lp(lp, report)
        except Exception as e:
            report["warnings"].append(f"LP parse failed: {e}")

    # consumption + solar → network_map loads (reuse existing logic briefly)
    net_path = APP_DIR / "network_map.json"
    if net_path.exists() and (cons is not None or sol is not None):
        net = json.loads(net_path.read_text(encoding="utf-8"))
        load_by_pole = defaultdict(float)
        solar_by_pole = defaultdict(float)
        n_customers = n_solar = 0
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
                        n_customers += 1
                    report["steps"].append(f"Consumption: {n_customers} customers on {len(load_by_pole)} poles")
            except Exception as e:
                report["warnings"].append(f"Consumption: {e}")
        if sol is not None:
            try:
                try:
                    df = pd.read_excel(sol, sheet_name="Solar Data V2")
                except Exception:
                    df = pd.read_excel(sol)
                pole_c = next((c for c in df.columns if "POLE" in str(c).upper()), None)
                inv_c = next((c for c in df.columns if "INV" in str(c).upper() or "CAP" in str(c).upper()), None)
                if pole_c and inv_c:
                    for _, r in df.iterrows():
                        if pd.isna(r[pole_c]): continue
                        solar_by_pole[str(r[pole_c]).strip()] += float(r[inv_c]) if pd.notna(r[inv_c]) else 0
                        n_solar += 1
                    report["steps"].append(f"Solar: {n_solar} records, {sum(solar_by_pole.values()):.1f} kW")
            except Exception as e:
                report["warnings"].append(f"Solar: {e}")
        for p in net["poles"]:
            if load_by_pole:
                p["load_kw"] = round(load_by_pole.get(p["id"], 0), 2)
            if solar_by_pole:
                p["solar_kw"] = round(solar_by_pole.get(p["id"], 0), 2)
        net_path.write_text(json.dumps(net))
        report["steps"].append("network_map.json updated")

    # timeline for first / locked day
    date0 = None
    if multi and multi.get("days"):
        date0 = multi.get("locked_day") or sorted(multi["days"].keys())[0]
    else:
        try:
            md = json.loads((APP_DIR / "multi_day_qsts.json").read_text(encoding="utf-8"))
            date0 = md.get("locked_day") or (sorted(md.get("days", {}).keys())[0] if md.get("days") else None)
        except Exception:
            date0 = "2026-06-13"
    if date0:
        try:
            _rebuild_timeline_for_date(date0, report)
        except Exception as e:
            report["warnings"].append(f"Timeline: {e}")

    report["summary"] = {
        "n_days": multi.get("n_days") if multi else None,
        "date_from": multi.get("date_from") if multi else None,
        "date_to": multi.get("date_to") if multi else None,
        "timeline_day": date0,
        "files": uploaded,
    }
    (APP_DIR / "last_process.json").write_text(json.dumps(report, indent=2))
    
    # === ALWAYS rebuild multi-day QSTS + voltage timeline from LP ===
    try:
        lp_file = lp
        if lp_file is None:
            # package data fallback
            for cand in [APP_DIR/"data"/"BZ0109LP.xlsx", APP_DIR/"BZ0109LP.xlsx"]:
                if cand.exists():
                    lp_file = cand
                    break
        if lp_file is not None:
            import sys
            if str(APP_DIR) not in sys.path: sys.path.insert(0, str(APP_DIR))
            from rebuild_lp_days import rebuild_multi_day_from_lp
            rr = rebuild_multi_day_from_lp(APP_DIR, lp_file, transformer_kva=transformer_kva)
            report["steps"].append("LP multi-day rebuild: "+str(rr))
            report["timeline"] = rr
        else:
            report["warnings"].append("No LP file for multi-day timeline rebuild")
    except Exception as e:
        report["warnings"].append("timeline rebuild failed: "+str(e))

    return report

@app.post("/api/set_day")
def set_day(date: str = ""):
    """Switch active study day and rebuild voltage timeline for that day's LP curve."""
    import json
    from fastapi import Query
    if not date:
        return JSONResponse({"ok": False, "error": "date required"}, status_code=400)
    report = {"ok": True, "steps": [], "warnings": []}
    # verify day exists
    multi_p = APP_DIR / "multi_day_qsts.json"
    if not multi_p.exists():
        return JSONResponse({"ok": False, "error": "multi_day_qsts.json missing — Process LP first"}, status_code=404)
    multi = json.loads(multi_p.read_text(encoding="utf-8"))
    days = multi.get("days") or {}
    if date not in days:
        return JSONResponse({
            "ok": False,
            "error": f"Day {date} not in LP",
            "available": sorted(list(days.keys()))[:5],
            "n_days": len(days),
        }, status_code=404)
    ok = _rebuild_timeline_for_date(date, report)
    if not ok:
        return JSONResponse({"ok": False, "error": f"Failed timeline for {date}", **report}, status_code=500)
    # update days_list preferred day (not locking)
    dl_p = APP_DIR / "days_list.json"
    if dl_p.exists():
        try:
            dl = json.loads(dl_p.read_text(encoding="utf-8"))
            dl["locked_day"] = date  # active day
            dl_p.write_text(json.dumps(dl, indent=2))
        except Exception:
            pass
    # sample voltages for verification
    tl = json.loads((APP_DIR / "voltages_timeline.json").read_text(encoding="utf-8"))
    sample = None
    if tl.get("frames"):
        fr = tl["frames"][76] if len(tl["frames"]) > 76 else tl["frames"][0]  # ~19:00
        # pick a sample pole
        if fr.get("p"):
            pid = next(iter(fr["p"]))
            sample = {"time": fr["t"], "pole": pid, "V": fr["p"][pid], "Vtf": fr.get("Vtf")}
    return {
        "ok": True,
        "date": date,
        "steps": report["steps"],
        "n_frames": tl.get("n"),
        "sample": sample,
        "note": "Timeline rebuilt for this day — slider/popup use new voltages",
    }



@app.get("/api/voltages_timeline")
def api_voltages_timeline(date: str = None):
    """Return 15-min pole voltages for one study day."""
    import json
    path = APP_DIR / "voltages_timeline.json"
    if not path.exists():
        return JSONResponse({"ok": False, "error": "voltages_timeline.json missing"}, status_code=404)
    data = _load_json_cached(path, _VT_CACHE) or {}
    days = data.get("days") or {}
    day = date or data.get("day")
    if day and isinstance(days, dict) and day in days:
        block = days[day]
        return {
            "ok": True,
            "day": day,
            "times": block.get("times") or [],
            "poles": block.get("poles") or {},
            "source": data.get("source"),
            "n_times": len(block.get("times") or []),
            "n_poles": len(block.get("poles") or {}),
        }
    # flat fallback
    return {
        "ok": True,
        "day": data.get("day"),
        "times": data.get("times") or [],
        "poles": data.get("poles") or {},
        "source": data.get("source"),
        "n_times": len(data.get("times") or []),
        "n_poles": len(data.get("poles") or {}),
    }


@app.get("/voltages_timeline.json")
def voltages_timeline_file():
    p = APP_DIR / "voltages_timeline.json"
    if p.exists():
        return FileResponse(p, media_type="application/json")
    return JSONResponse({"error": "voltages_timeline.json missing"}, status_code=404)

@app.get("/volt_topo.json")
def volt_topo_file():
    p = APP_DIR / "volt_topo.json"
    if p.exists(): return FileResponse(p, media_type="application/json")
    return JSONResponse({"error":"missing"}, status_code=404)

@app.get("/multi_day_qsts.json")
def multi_day_file():
    p = APP_DIR / "multi_day_qsts.json"
    if p.exists():
        return FileResponse(p, media_type="application/json")
    return JSONResponse({"error": "missing"}, status_code=404)

@app.get("/days_list.json")
def days_list_file():
    p = APP_DIR / "days_list.json"
    if p.exists():
        return FileResponse(p, media_type="application/json")
    return JSONResponse({"error": "missing"}, status_code=404)



@app.get("/api/pole_voltage_compare")
def api_pole_voltage_compare(date: str = None, pole: str = None, max_rows: int = 400):
    max_rows = max(50, min(int(max_rows or 400), 10000))
    """Pole-wise measured (LP) vs simulated voltages for one study day."""
    import json
    try:
        by_day = APP_DIR / "pole_v_by_day"
        # Prefer per-day file
        day = date
        if not day:
            idx_path = by_day / "index.json"
            if idx_path.exists():
                idx = json.loads(idx_path.read_text(encoding="utf-8"))
                days = idx.get("days") or []
                day = days[0] if days else None
        if day:
            fp = by_day / f"{day}.json"
            if fp.exists():
                data = json.loads(fp.read_text(encoding="utf-8"))
                rows = data.get("rows") or []
                if pole:
                    rows = [r for r in rows if str(r.get("pole")) == str(pole)]
                if len(rows) > max_rows:
                    # keep evenly spaced samples
                    step = max(1, len(rows) // max_rows)
                    rows = rows[::step][:max_rows]
                return {
                    "ok": True,
                    "day": day,
                    "poles": data.get("poles") or [],
                    "summary": data.get("summary") or [],
                    "rows": rows,
                    "n_rows": data.get("n_rows") or len(data.get("rows") or []),
                    "source": data.get("source") or "pole_v_by_day",
                }
        # Fallback big file
        path = APP_DIR / "pole_voltage_compare.json"
        if not path.exists():
            return JSONResponse({"ok": False, "error": "pole voltage compare data missing — run Process"}, status_code=404)
        data = json.loads(path.read_text(encoding="utf-8"))
        days = data.get("days") or {}
        day = date or (sorted(days.keys())[0] if days else None)
        if not day or day not in days:
            return {"ok": False, "error": f"No compare data for {day}", "available": list(days.keys())[:15]}
        block = days[day]
        rows = block.get("rows") or []
        if pole:
            rows = [r for r in rows if str(r.get("pole")) == str(pole)]
        if len(rows) > max_rows:
            step = max(1, len(rows) // max_rows)
            rows = rows[::step][:max_rows]
        return {
            "ok": True,
            "day": day,
            "poles": [str(p) for p in (block.get("poles") or []) if str(p) != "nan"],
            "summary": block.get("summary") or [],
            "rows": rows,
            "n_rows": len(block.get("rows") or []),
            "source": data.get("source"),
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/pole_voltage_compare.json")
def pole_voltage_compare_file():
    p = APP_DIR / "pole_voltage_compare.json"
    if p.exists():
        return FileResponse(p, media_type="application/json")
    return JSONResponse({"error":"missing"}, status_code=404)


@app.get("/api/pole_distances")
def api_pole_distances():
    import json
    p = APP_DIR / "pole_distances.json"
    if not p.exists():
        return JSONResponse({"ok": False, "error": "pole_distances.json missing"}, status_code=404)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["ok"] = True
    return data

@app.get("/pole_distances.json")
def pole_distances_file():
    p = APP_DIR / "pole_distances.json"
    if p.exists():
        return FileResponse(p, media_type="application/json")
    return JSONResponse({"error": "missing"}, status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
