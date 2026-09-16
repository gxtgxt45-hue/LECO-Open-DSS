"""
OpenDSS Script Generator for LECO Distribution Networks.
Generates complete, valid, standard OpenDSS (.dss) files for transformers, distributors, poles, loads, and solar PV systems.
"""

from pathlib import Path
import json

def generate_dss_files(network_map: dict, load_shape_data: list = None, solar_shape_data: list = None, tx_kva: int = 250, output_dir: Path = None) -> dict:
    """
    Generates OpenDSS files:
    - master.dss
    - linecodes.dss
    - lines.dss
    - loads.dss
    - pvsystem.dss
    Returns dict mapping file names to string content (and saves them if output_dir provided).
    """
    poles = network_map.get("poles", [])
    lines = network_map.get("lines", [])
    tx_name = network_map.get("transformer_id", "BZ0109")

    # 1. linecodes.dss
    linecodes_dss = f"""! OpenDSS Linecode Definitions for LECO LV Conductors
! Linecodes based on standard LECO LV 400V Overhead Lines / ABC Cable

New Linecode.ABC_70 nphases=3 r1=0.443 x1=0.09 r0=1.329 x0=0.27 units=km
New Linecode.Fly_AAC nphases=3 r1=0.270 x1=0.30 r0=0.810 x0=0.90 units=km
New Linecode.Wasp_AAC nphases=3 r1=0.160 x1=0.28 r0=0.480 x0=0.84 units=km
New Linecode.Default_LV nphases=3 r1=0.350 x1=0.15 r0=1.050 x0=0.45 units=km
"""

    # 2. master.dss
    master_dss = f"""! OpenDSS Master Circuit File for LECO Transformer {tx_name}
! Generated automatically by GridVision OpenDSS Studio

Clear

! Define 11kV Substation Source (Base 11kV L-L, 50 Hz)
New Circuit.LECO_{tx_name} basekv=11.0 pu=1.00 angle=0 frequency=50 phases=3

! Define 11kV / 0.4kV Distribution Transformer ({tx_kva} kVA)
New Transformer.Tx_{tx_name} Phases=3 Windings=2 Wdg=1 Bus=SourceBus kV=11.0 kVA={tx_kva} Conn=Delta Wdg=2 Bus=TX_LV_BUS.1.2.3.0 kV=0.400 kVA={tx_kva} Conn=Wye %R=1.0 XHL=4.5

! Load Conductor Linecodes
Redirect linecodes.dss

! Load Network Line Topology
Redirect lines.dss

! Load Customer Connections
Redirect loads.dss

! Load Solar Rooftop PV Inverters
Redirect pvsystem.dss

! Set Voltage Bases
Set voltagebases=[11.0, 0.400]
CalcVoltageBases

! Set Control & Solve Options
Set Mode=Snapshot
Solve

! Summary Outputs
Show Voltages LN Nodes
Show Losses
"""

    # 3. lines.dss
    lines_list = []
    lines_list.append(f"! OpenDSS Pole-to-Pole Line Segments for {tx_name}\n")
    
    # Connect Tx_LV to first pole if applicable
    first_pole = poles[0]["id"] if poles else "P1"
    lines_list.append(f"New Line.L_TX_TO_{first_pole} Bus1=TX_LV_BUS.1.2.3.0 Bus2={first_pole}.1.2.3.0 Linecode=ABC_70 Length=0.010 Units=km Phases=3")

    for idx, l in enumerate(lines):
        p1 = str(l.get("from") or l.get("bus1") or f"P{idx}").replace("/", "_").replace("-", "_")
        p2 = str(l.get("to") or l.get("bus2") or f"P{idx+1}").replace("/", "_").replace("-", "_")
        length_m = float(l.get("length_m") or l.get("length") or 40.0)
        length_km = max(length_m / 1000.0, 0.005)
        cond = l.get("conductor") or "ABC_70"
        code = "ABC_70" if "ABC" in cond else ("Fly_AAC" if "Fly" in cond else "Default_LV")
        line_name = f"L_{p1}_{p2}"
        lines_list.append(f"New Line.{line_name} Bus1={p1}.1.2.3.0 Bus2={p2}.1.2.3.0 Linecode={code} Length={length_km:.4f} Units=km Phases=3")

    lines_dss = "\n".join(lines_list)

    # 4. loads.dss
    loads_list = []
    loads_list.append(f"! OpenDSS Customer Load Definitions at Distributor Poles ({tx_name})\n")
    
    if load_shape_data and len(load_shape_data) == 96:
        mult_str = " ".join([f"{v:.4f}" for v in load_shape_data])
        loads_list.append(f"New LoadShape.DailyCustomerShape npts=96 minterval=15 mult=({mult_str})\n")
        shape_ref = "daily=DailyCustomerShape "
    else:
        shape_ref = ""

    for idx, p in enumerate(poles):
        pole_id = str(p.get("id") or f"P{idx+1}").replace("/", "_").replace("-", "_")
        load_kw = float(p.get("load_kw") or 0.0)
        cust_count = int(p.get("customers") or (1 if load_kw > 0 else 0))
        
        if load_kw > 0 or cust_count > 0:
            phase_num = (idx % 3) + 1
            phase_v_kv = 0.230
            kw_val = max(load_kw if load_kw > 0 else cust_count * 1.5, 0.5)
            load_name = f"Load_{pole_id}_Ph{phase_num}"
            loads_list.append(
                f"New Load.{load_name} Bus1={pole_id}.{phase_num}.0 Phases=1 kV={phase_v_kv} kW={kw_val:.2f} PF=0.95 Model=1 Vminpu=0.85 {shape_ref}"
            )

    loads_dss = "\n".join(loads_list)

    # 5. pvsystem.dss
    pv_list = []
    pv_list.append(f"! OpenDSS Rooftop PV System Inverters on Poles ({tx_name})\n")
    
    if solar_shape_data and len(solar_shape_data) == 96:
        s_mult_str = " ".join([f"{v:.4f}" for v in solar_shape_data])
        pv_list.append(f"New LoadShape.DailySolarShape npts=96 minterval=15 mult=({s_mult_str})\n")
        pv_shape_ref = "daily=DailySolarShape "
    else:
        pv_shape_ref = ""

    for idx, p in enumerate(poles):
        pole_id = str(p.get("id") or f"P{idx+1}").replace("/", "_").replace("-", "_")
        solar_kw = float(p.get("solar_kw") or 0.0)
        
        if solar_kw > 0:
            phase_num = (idx % 3) + 1
            phase_v_kv = 0.230
            pv_name = f"PV_{pole_id}_Ph{phase_num}"
            pv_list.append(
                f"New PVSystem.{pv_name} Bus1={pole_id}.{phase_num}.0 Phases=1 kV={phase_v_kv} kVA={solar_kw:.2f} pmpp={solar_kw:.2f} pf=1.0 %cutin=0.1 %cutout=0.1 {pv_shape_ref}"
            )

    pv_dss = "\n".join(pv_list)

    result = {
        "master.dss": master_dss,
        "linecodes.dss": linecodes_dss,
        "lines.dss": lines_dss,
        "loads.dss": loads_dss,
        "pvsystem.dss": pv_dss,
    }

    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        for fname, content in result.items():
            (output_dir / fname).write_text(content, encoding="utf-8")

    return result
