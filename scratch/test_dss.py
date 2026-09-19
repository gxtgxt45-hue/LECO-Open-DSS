import opendssdirect as dss
from pathlib import Path

master_path = Path('scratch/LECO_BZ0109_OpenDSS/master.dss').resolve()
print("Compiling OpenDSS Master File:", master_path.as_posix())

dss.run_command(f'Compile "{master_path.as_posix()}"')

print("Solution Converged:", dss.Solution.Converged())
print("Total Circuit Buses:", len(dss.Circuit.AllBusNames()))
print("Total Circuit Loads:", len(dss.Loads.AllNames()))
print("Total PV Systems:", len(dss.PVsystems.AllNames()))

# Print sample node voltages
buses = dss.Circuit.AllBusNames()[:5]
for b in buses:
    dss.Circuit.SetActiveBus(b)
    v_mag = dss.Bus.VMagAngle()[::2]
    v_pu = [round(v / 230.0, 4) for v in v_mag]
    print(f"Bus {b}: V (Volts) = {[round(v, 1) for v in v_mag]} | p.u. = {v_pu}")
