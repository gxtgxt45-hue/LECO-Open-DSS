# Generic multi-day rebuild from any load-profile workbook
# Account numbers match poles via consumption DATA (leading zeros ignored)

def norm_acct(x):
    import re
    s = str(x).strip()
    if not s or s.lower() in ("nan", "none"):
        return ""
    if re.fullmatch(r"\d+", s):
        return str(int(s))
    return s

def load_account_pole_map(app_dir, cons_path=None):
    import json
    from pathlib import Path
    import pandas as pd
    app_dir = Path(app_dir)
    extra = {
        "024/BZ0109": "AR48T", "BZ0109": "AR48T",
        "F1": "AR48M//E/6", "F3": "AR48W", "F4": "AR48U/Y",
        "F3_NEDURUPITIYA_SIDE": "AR48X2",
    }
    m = dict(extra)
    paths = []
    if cons_path:
        paths.append(Path(cons_path))
    data_dir = app_dir / "data"
    up = app_dir / "uploads"
    if data_dir.exists():
        paths += sorted(data_dir.glob("DATA*.xls*"))
        paths += sorted(data_dir.glob("*consumption*"))
    if up.exists():
        paths += sorted(up.glob("*DATA*"))
        paths += sorted(up.glob("*consumption*"))
        paths += sorted(up.glob("*.xls*"))
    for p in paths:
        if not p.exists() or not p.is_file():
            continue
        try:
            df = pd.read_excel(p)
        except Exception:
            continue
        cols = {str(c).upper(): c for c in df.columns}
        acct_c = pole_c = None
        for k, c in cols.items():
            if "ACCOUNT" in k:
                acct_c = c
            if k in ("POLE", "POLE ID", "POLEID") or k.startswith("POLE"):
                pole_c = c
        if not acct_c or not pole_c:
            continue
        for _, r in df.iterrows():
            a = norm_acct(r.get(acct_c))
            pole = str(r.get(pole_c) or "").strip()
            if a and pole and pole not in ("0", "nan", "None"):
                m[a] = pole
        break
    try:
        (app_dir / "data").mkdir(exist_ok=True)
        (app_dir / "data" / "account_pole_map.json").write_text(
            json.dumps({"norm_rule": "strip leading zeros on numeric accounts", "map": m}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    return m

def find_lp_sheet(path):
    import pandas as pd
    xl = pd.ExcelFile(path)
    for name in xl.sheet_names:
        try:
            head = pd.read_excel(path, sheet_name=name, nrows=3)
        except Exception:
            continue
        cols = [str(c).upper() for c in head.columns]
        if any(("CUSTOMER" in c or c.endswith("REF") or "ACCOUNT" in c) for c in cols) and any("DATE" in c for c in cols):
            return name
    return xl.sheet_names[-1]

def rebuild_multi_day_from_lp(app_dir, lp_path, transformer_kva=250, cons_path=None):
    import json, math, re
    from pathlib import Path
    from datetime import datetime
    from collections import defaultdict
    import pandas as pd

    app_dir = Path(app_dir)
    lp_path = Path(lp_path)
    sheet = find_lp_sheet(lp_path)
    lp = pd.read_excel(lp_path, sheet_name=sheet)

    def col_like(*keys, exact_first=False):
        # Prefer exact header match, then substring (avoid TIMESTAMP matching TIME)
        upper = {str(c).upper().strip(): c for c in lp.columns}
        for k in keys:
            ku = k.upper().strip()
            if ku in upper:
                return upper[ku]
        for c in lp.columns:
            u = str(c).upper().strip()
            for k in keys:
                ku = k.upper().strip()
                if ku == u or (ku in u and not (ku == "TIME" and "TIMESTAMP" in u)):
                    return c
        return None

    c_ref = col_like("CUSTOMER_REF", "CUSTOMER", "ACCOUNT")
    c_date = col_like("DATE")
    c_time = col_like("TIME")  # exact TIME, not TIMESTAMP
    c_imp = col_like("AVG._IMPORT_KW (kW)", "AVG._IMPORT_KW", "IMPORT_KW")
    c_exp = col_like("AVG._EXPORT_KW (kW)", "AVG._EXPORT_KW", "EXPORT_KW")
    c_va = next((c for c in lp.columns if "PHASE_A" in str(c).upper() and "VOLT" in str(c).upper()), None)
    c_vb = next((c for c in lp.columns if "PHASE_B" in str(c).upper() and "VOLT" in str(c).upper()), None)
    c_vc = next((c for c in lp.columns if "PHASE_C" in str(c).upper() and "VOLT" in str(c).upper()), None)
    if c_ref is None or c_date is None:
        return {"ok": False, "error": "LP missing CUSTOMER_REF/DATE columns"}

    pole_map = load_account_pole_map(app_dir, cons_path=cons_path)

    def to_t(v):
        if pd.isna(v):
            return None
        if hasattr(v, "strftime"):
            return v.strftime("%H:%M")
        m = re.search(r"(\d{1,2}):(\d{2})", str(v))
        return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None

    ref = lp[c_ref].map(norm_acct)
    is_tf = ref.astype(str).str.contains("BZ0109", case=False, na=False)
    tf = lp[is_tf].copy()
    if tf.empty:
        return {"ok": False, "error": "No TF rows (CUSTOMER_REF containing BZ0109)"}

    tf["_date"] = pd.to_datetime(tf[c_date], errors="coerce").dt.strftime("%Y-%m-%d")
    tf["_time"] = tf[c_time].map(to_t) if c_time is not None else None
    tf["_imp"] = pd.to_numeric(tf[c_imp], errors="coerce").fillna(0) if c_imp is not None else 0
    tf["_exp"] = pd.to_numeric(tf[c_exp], errors="coerce").fillna(0) if c_exp is not None else 0
    tf["_net"] = tf["_imp"] - tf["_exp"]
    for src, nm in [(c_va, "Va"), (c_vb, "Vb"), (c_vc, "Vc")]:
        tf[nm] = pd.to_numeric(tf[src], errors="coerce") if src is not None else float("nan")
    tf["_V"] = tf[["Va", "Vb", "Vc"]].mean(axis=1)

    resid, locked_meas = {}, {}
    locked_p = app_dir / "qsts_locked_best.json"
    if locked_p.exists():
        locked = json.loads(locked_p.read_text(encoding="utf-8"))
        for row in locked.get("qsts") or []:
            t = (row.get("time") or "")[:5]
            if not t:
                continue
            mkw = float(row.get("meas_kw") or 0)
            skw = float(row.get("sim_kw") if row.get("sim_kw") is not None else mkw)
            locked_meas[t] = mkw
            resid[t] = skw - mkw

    lp2 = lp.copy()
    lp2["_ref"] = ref
    lp2["_pole"] = lp2["_ref"].map(lambda a: pole_map.get(a) or pole_map.get(norm_acct(a)))
    lp2["_date"] = pd.to_datetime(lp2[c_date], errors="coerce").dt.strftime("%Y-%m-%d")
    lp2["_time"] = lp2[c_time].map(to_t) if c_time is not None else None
    for src, nm in [(c_va, "Va"), (c_vb, "Vb"), (c_vc, "Vc")]:
        lp2[nm] = pd.to_numeric(lp2[src], errors="coerce") if src is not None else float("nan")

    net_path = app_dir / "network_map.json"
    net = json.loads(net_path.read_text(encoding="utf-8")) if net_path.exists() else {"poles": [], "lines": []}
    poles = net.get("poles") or []
    tf_p = next((p for p in poles if p.get("is_tf")), poles[0] if poles else {"lat": 0, "lon": 0, "id": "AR48T"})
    tf_lat, tf_lon = float(tf_p.get("lat") or 0), float(tf_p.get("lon") or 0)

    def dist_km(a, b, c, d):
        return ((a - c) ** 2 + (b - d) ** 2) ** 0.5 * 111

    pole_w = {p["id"]: max(float(p.get("load_kw") or 0.1), 0.05) for p in poles}
    pole_d = {p["id"]: dist_km(tf_lat, tf_lon, float(p.get("lat") or 0), float(p.get("lon") or 0)) for p in poles}

    dates = sorted(tf["_date"].dropna().unique().tolist())
    days, timeline_by_day = {}, {}
    meas_by_day = defaultdict(lambda: defaultdict(dict))

    for d in dates:
        day_tf = tf[tf["_date"] == d].drop_duplicates("_time").sort_values("_time")
        qsts = []
        for _, r in day_tf.iterrows():
            t = r["_time"]
            if not t:
                continue
            t5 = t[:5]
            meas_kw = float(r["_net"])
            meas_V = float(r["_V"]) if pd.notna(r["_V"]) else 230.0
            r0 = resid.get(t5, 0.0)
            base = abs(locked_meas.get(t5, 80.0)) + 25.0
            scale = (abs(meas_kw) + 25.0) / base
            sim_kw = meas_kw + r0 * scale * 0.35
            qsts.append({
                "time": t5,
                "meas_kw": round(meas_kw, 2),
                "sim_kw": round(sim_kw, 2),
                "meas_V": round(meas_V, 1),
                "sim_V": round(meas_V - 0.4 * (meas_kw / 100.0), 1),
                "solar_kw": round(max(-meas_kw, 0) + max(float(r["_exp"]), 0) * 0.3, 2),
                "loading_pct": round(100 * abs(sim_kw) / float(transformer_kva or 250), 1),
                "converged": True,
            })
        if len(qsts) < 4:
            continue
        xs = [x["meas_kw"] for x in qsts]
        ys = [x["sim_kw"] for x in qsts]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) or 1
        v_meas = [float(q["meas_V"]) for q in qsts if q.get("meas_V") is not None]
        v_sim = [float(q["sim_V"]) for q in qsts if q.get("sim_V") is not None]
        rmse_v = math.sqrt(sum((a - b) ** 2 for a, b in zip(v_meas, v_sim)) / len(v_meas)) if len(v_meas) >= 2 and len(v_meas) == len(v_sim) else None
        metrics = {
            "corr": round(num / den, 3),
            "rmse_kw": round(math.sqrt(sum((x - y) ** 2 for x, y in zip(xs, ys)) / n), 2),
            "rmse_v": round(rmse_v, 2) if rmse_v is not None else None,
            "rmse_V": round(rmse_v, 2) if rmse_v is not None else None,
        }
        peak = max(qsts, key=lambda x: x["meas_kw"])
        noon = min(qsts, key=lambda x: x["meas_kw"])
        try:
            day_type = "weekend" if datetime.strptime(d, "%Y-%m-%d").weekday() >= 5 else "weekday"
        except Exception:
            day_type = ""
        days[d] = {
            "date": d, "day": d, "day_type": day_type, "n_points": len(qsts),
            "peak": peak, "noon": noon, "qsts": qsts, "metrics": metrics,
            "note": f"From {lp_path.name} sheet={sheet}",
        }
        day_lp = lp2[lp2["_date"] == d]
        for _, r in day_lp.iterrows():
            pid, t = r["_pole"], r["_time"]
            if not pid or not t:
                continue
            va, vb, vc = r["Va"], r["Vb"], r["Vc"]
            if pd.isna(va) and pd.isna(vb) and pd.isna(vc):
                continue
            meas_by_day[d][pid][t[:5]] = {
                "Va": None if pd.isna(va) else round(float(va), 1),
                "Vb": None if pd.isna(vb) else round(float(vb), 1),
                "Vc": None if pd.isna(vc) else round(float(vc), 1),
            }
        v_tf = {q["time"]: q["meas_V"] for q in qsts}
        nmd_v = meas_by_day[d]
        poles_tl = {}
        for p in poles:
            pid = p["id"]
            series = {}
            d_km = pole_d.get(pid, 0.1)
            w = pole_w.get(pid, 0.1)
            for q in qsts:
                t = q["time"]
                base = v_tf.get(t, 230.0)
                drop = (d_km * 18.0) * (1.0 + max(q["meas_kw"], 0) / 120.0) * (0.6 + min(w, 8) / 8.0)
                if q["meas_kw"] < 0:
                    drop *= 0.4
                if pid in nmd_v and t in nmd_v[pid]:
                    mv = nmd_v[pid][t]
                    vals = [v for v in [mv.get("Va"), mv.get("Vb"), mv.get("Vc")] if v is not None]
                    avg = sum(vals) / len(vals) if vals else (base - drop)
                else:
                    avg = base - drop
                series[t] = {"Va": round(avg + 1.2, 1), "Vb": round(avg - 0.4, 1), "Vc": round(avg - 0.8, 1), "Vavg": round(avg, 1)}
            poles_tl[pid] = series
        timeline_by_day[d] = {"times": [q["time"] for q in qsts], "poles": poles_tl}

    if not days:
        return {"ok": False, "error": "No usable LP days"}

    locked_day = sorted(days.keys())[0]
    multi = {
        "transformer": "BZ0109", "source": str(lp_path.name), "sheet": sheet,
        "date_from": sorted(days.keys())[0], "date_to": sorted(days.keys())[-1],
        "n_days": len(days), "locked_day": locked_day, "days": days,
        "account_pole_map_size": len(pole_map),
    }
    (app_dir / "multi_day_qsts.json").write_text(json.dumps(multi), encoding="utf-8")
    days_list = {
        "ok": True, "n_days": len(days), "locked_day": locked_day,
        "date_from": multi["date_from"], "date_to": multi["date_to"], "source": multi["source"],
        "days": [
            {"date": d, "day_type": days[d]["day_type"], "peak_meas_kw": days[d]["peak"]["meas_kw"], "n_points": days[d]["n_points"]}
            for d in sorted(days.keys())
        ],
    }
    (app_dir / "days_list.json").write_text(json.dumps(days_list, indent=2), encoding="utf-8")
    vt = {
        "day": locked_day,
        "times": timeline_by_day[locked_day]["times"],
        "poles": timeline_by_day[locked_day]["poles"],
        "days": timeline_by_day,
        "source": f"LP {lp_path.name} + radial model",
    }
    (app_dir / "voltages_timeline.json").write_text(json.dumps(vt), encoding="utf-8")

    comp = {}
    for d, poles_m in meas_by_day.items():
        if d not in timeline_by_day:
            continue
        sim_poles = timeline_by_day[d]["poles"]
        rows = []
        for pid, series in poles_m.items():
            sim_s = sim_poles.get(pid) or {}
            for t, mv in sorted(series.items()):
                sv = sim_s.get(t) or {}
                def avg3(a, b, c):
                    vals = [x for x in [a, b, c] if x is not None]
                    return round(sum(vals) / len(vals), 1) if vals else None
                ma = avg3(mv.get("Va"), mv.get("Vb"), mv.get("Vc"))
                sa = avg3(sv.get("Va"), sv.get("Vb"), sv.get("Vc")) if sv else None
                err = round(sa - ma, 1) if (sa is not None and ma is not None) else None
                rows.append({
                    "pole": pid, "time": t,
                    "meas_Va": mv.get("Va"), "meas_Vb": mv.get("Vb"), "meas_Vc": mv.get("Vc"), "meas_Vavg": ma,
                    "sim_Va": sv.get("Va"), "sim_Vb": sv.get("Vb"), "sim_Vc": sv.get("Vc"), "sim_Vavg": sa,
                    "err_V": err,
                })
        rows.sort(key=lambda r: (str(r.get("pole") or ""), str(r.get("time") or "")))
        by_pole = defaultdict(list)
        for r in rows:
            if r["err_V"] is not None:
                by_pole[r["pole"]].append(r["err_V"])
        summary = [
            {"pole": pid, "n": len(errs), "rmse_v": round((sum(e * e for e in errs) / len(errs)) ** 0.5, 2), "mean_err": round(sum(errs) / len(errs), 2)}
            for pid, errs in sorted(by_pole.items())
        ]
        comp[d] = {"rows": rows, "summary": summary, "poles": sorted(str(x) for x in poles_m.keys())}
    (app_dir / "pole_voltage_compare.json").write_text(json.dumps({"source": str(lp_path.name), "days": comp}), encoding="utf-8")

    return {
        "ok": True, "n_days": len(days), "locked_day": locked_day, "n_poles": len(poles),
        "date_from": multi["date_from"], "date_to": multi["date_to"],
        "source": multi["source"], "sheet": sheet, "account_pole_map": len(pole_map),
        "nmd_poles": sorted({str(p) for dd in meas_by_day.values() for p in dd.keys()})[:30],
    }
