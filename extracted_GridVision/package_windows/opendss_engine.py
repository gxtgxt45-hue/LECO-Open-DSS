"""BZ0109 engine — multi-day locked / residual profiles + map support."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

OUT = Path(__file__).parent
LOCKED = {
    "self_cons": 0.20,
    "solar_scale": 1.0,
    "export_target": True,
    "BASE_KW": 45.0,
    "transformer_kva": 250,
}
DEFAULT_MODEL = {
    "GP11": 2, "GP12": 2, "GP1-G": 2, "D1": 2, "I12": 1,
    "R1": 2, "R2": 2, "STL1": 2, "STL2": 2, "TEMP1": 2, "NPLUS": 2,
}

def _load_multi() -> Dict[str, Any]:
    path = OUT / "multi_day_qsts.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}

def _load_locked_single() -> Dict[str, Any]:
    path = OUT / "qsts_locked_best.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}

def list_days() -> Dict[str, Any]:
    multi = _load_multi()
    if not multi:
        locked = _load_locked_single()
        d = locked.get("day", "2026-06-13")
        return {
            "ok": True,
            "n_days": 1,
            "date_from": d,
            "date_to": d,
            "locked_day": d,
            "days": [{"date": d, "day_type": locked.get("day_type", "weekend"),
                      "peak_meas_kw": None, "min_net_kw": None,
                      "corr": (locked.get("metrics") or {}).get("corr"),
                      "rmse_kw": (locked.get("metrics") or {}).get("rmse_kw")}],
        }
    return {
        "ok": True,
        "n_days": multi.get("n_days"),
        "date_from": multi.get("date_from"),
        "date_to": multi.get("date_to"),
        "locked_day": multi.get("locked_day"),
        "days": multi.get("summary", []),
    }

def get_day(date: Optional[str] = None) -> Dict[str, Any]:
    multi = _load_multi()
    if multi and multi.get("days"):
        if not date:
            date = multi.get("locked_day") or multi.get("date_from")
        rec = multi["days"].get(date)
        if not rec:
            return {"ok": False, "error": f"No data for {date}", "available": list(multi["days"].keys())}
        return {"ok": True, **rec}
    locked = _load_locked_single()
    if not locked:
        return {"ok": False, "error": "No QSTS data"}
    return {
        "ok": True,
        "date": locked.get("day"),
        "day_type": locked.get("day_type"),
        "model": "full_export_target_locked",
        "metrics": locked.get("metrics"),
        "qsts": locked.get("qsts", []),
        "feeders": locked.get("feeders"),
        "solar_inv_kw": locked.get("solar_inv_kw"),
    }

def get_status() -> Dict[str, Any]:
    days = list_days()
    day = get_day(None)
    metrics = day.get("metrics") if day.get("ok") else None
    return {
        "ok": True,
        "engine": "Multi-day profiles (30 days) + locked OpenDSS residual",
        "transformer_default_kva": LOCKED["transformer_kva"],
        "self_cons": LOCKED["self_cons"],
        "export_target": LOCKED["export_target"],
        "has_qsts": True,
        "metrics": metrics,
        "day": day.get("date"),
        "n_days": days.get("n_days"),
        "date_from": days.get("date_from"),
        "date_to": days.get("date_to"),
        "locked_day": days.get("locked_day"),
        "feeders": day.get("feeders") or [],
        "solar_inv_kw": day.get("solar_inv_kw"),
        "net_metered_accounts": None,
    }

def run_snapshot(mode: str = "noon", transformer_kva: int = 250, peak_factor: float = 2.8,
                 date: Optional[str] = None) -> Dict[str, Any]:
    day = get_day(date)
    if not day.get("ok"):
        return day
    qsts = day.get("qsts") or []
    if not qsts:
        return {"ok": False, "error": "No QSTS points"}
    if mode == "peak":
        idx = max(range(len(qsts)), key=lambda i: qsts[i].get("meas_kw") or -1e9)
        label = "PEAK (max import)"
    else:
        idx = min(range(len(qsts)), key=lambda i: qsts[i].get("meas_kw") or 1e9)
        label = "SOLAR NOON (min net / max export)"
    row = qsts[idx]
    load_pct = row.get("loading_pct")
    if load_pct is not None and transformer_kva != 250:
        load_pct = round(float(load_pct) * 250 / max(transformer_kva, 1), 1)
    return {
        "ok": True,
        "mode": mode,
        "label": label,
        "date": day.get("date"),
        "day_type": day.get("day_type"),
        "time": row.get("time"),
        "meas_kw": row.get("meas_kw"),
        "sim_kw": row.get("sim_kw"),
        "meas_V": row.get("meas_V"),
        "sim_V": row.get("sim_V"),
        "solar_kw": row.get("solar_kw"),
        "loading_pct": load_pct,
        "transformer_kva": transformer_kva,
        "peak_factor": peak_factor,
        "model": day.get("model"),
        "metrics": day.get("metrics"),
    }

def run_comparison(transformer_kva: int = 250, peak_factor: float = 2.8,
                   date: Optional[str] = None) -> Dict[str, Any]:
    return {
        "ok": True,
        "peak": run_snapshot("peak", transformer_kva, peak_factor, date),
        "noon": run_snapshot("noon", transformer_kva, peak_factor, date),
    }

def run_qsts_full(date: Optional[str] = None) -> Dict[str, Any]:
    day = get_day(date)
    if not day.get("ok"):
        return day
    return {
        "ok": True,
        "date": day.get("date"),
        "day": day.get("date"),
        "day_type": day.get("day_type"),
        "model": day.get("model"),
        "note": day.get("note"),
        "settings": LOCKED,
        "metrics": day.get("metrics"),
        "peak": day.get("peak"),
        "noon": day.get("noon"),
        "qsts": day.get("qsts", []),
        "solar_inv_kw": day.get("solar_inv_kw"),
        "feeders": day.get("feeders") or [],
    }
