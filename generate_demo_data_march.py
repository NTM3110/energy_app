from datetime import datetime, timedelta
import csv
import random
from collections import defaultdict

# ================= CONFIG =================
YEAR = 2026
MONTH = 3
OUT = f"demo_energy_{YEAR}_{MONTH:02d}_final.csv"

INTERVAL = timedelta(minutes=30)
random.seed(42)

RTS_METERS = ["SOLAR_01", "SOLAR_02", "SOLAR_03", "SOLAR_04"]
BESS_METERS = ["BESS_01", "BESS_02", "BESS_03", "BESS_04"]

RTS_RANGE = (3.0, 6.0)        # always > 0
BESS_RANGE = (1.0, 3.5)       # always > 0 when healthy
SELF_RANGE = (1.0, 3.0)       # TRUE self consumption
K_RANGE = (0.01, 0.03)

# ================= FAULT SCHEDULE (SIMULATION ONLY) =================
FAULT_BLOCKS = [
    ("F02_NO_GRID", datetime(2026, 3, 5, 0), datetime(2026, 3, 6, 0)),
    ("F03_NO_INTERCONNECT", datetime(2026, 3, 10, 8), datetime(2026, 3, 10, 12)),
    ("F05_NO_SELF", datetime(2026, 3, 15, 6), datetime(2026, 3, 15, 12)),
    ("F06_ONLY_BESS_FAULTY", datetime(2026, 3, 18, 0), datetime(2026, 3, 20, 0)),
    ("F04_ONLY_RTS_FAULTY", datetime(2026, 3, 23, 0), datetime(2026, 3, 24, 0)),
    ("F07_BOTH_BESS_RTS_FAULTY", datetime(2026, 3, 27, 8), datetime(2026, 3, 27, 16)),
]

def month_range(y, m):
    s = datetime(y, m, 1)
    e = datetime(y, m + 1, 1) if m < 12 else datetime(y + 1, 1, 1)
    return s, e

def sim_state(ts):
    for code, s, e in FAULT_BLOCKS:
        if s <= ts < e:
            return code
    return "F01_NORMAL"

# ================= GENERATE DATA =================
start, end = month_range(YEAR, MONTH)

with open(OUT, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["meter_serial", "ts_start", "ts_end", "import_kwh", "export_kwh"])

    ts = start
    while ts < end:
        ts_end = ts + INTERVAL
        state = sim_state(ts)

        # ---- TRUE physical values ----
        rts = {m: round(random.uniform(*RTS_RANGE), 4) for m in RTS_METERS}
        bess = {m: round(random.uniform(*BESS_RANGE), 4) for m in BESS_METERS}
        true_self = round(random.uniform(*SELF_RANGE), 4)

        # ---- Apply source faults (reported values only) ----
        if state in ("F04_ONLY_RTS_FAULTY", "F07_BOTH_BESS_RTS_FAULTY"):
            rts["SOLAR_02"] = 0.0

        if state in ("F06_ONLY_BESS_FAULTY", "F07_BOTH_BESS_RTS_FAULTY"):
            bess["BESS_03"] = 0.0

        # ---- Compute GRID from TRUE physics ----
        grid_true = max(sum(rts.values()) + sum(bess.values()) - true_self, 0.0)

        # ---- Reported meters ----
        reported_self = 0.0 if state == "F05_NO_SELF" else true_self
        reported_grid = 0.0 if state == "F02_NO_GRID" else round(grid_true, 4)

        reported_dest = round(grid_true * (1 - random.uniform(*K_RANGE)), 4)
        if state == "F03_NO_INTERCONNECT":
            reported_dest = 0.0

        # ---- Write rows ----
        for m in RTS_METERS:
            w.writerow([m, ts.isoformat(), ts_end.isoformat(), 0.0, rts[m]])

        for m in BESS_METERS:
            w.writerow([m, ts.isoformat(), ts_end.isoformat(), 0.0, bess[m]])

        w.writerow(["SELF_01", ts.isoformat(), ts_end.isoformat(), reported_self, 0.0])
        w.writerow(["GRID_01", ts.isoformat(), ts_end.isoformat(), 0.0, reported_grid])
        w.writerow(["DEST_01", ts.isoformat(), ts_end.isoformat(), reported_dest, 0.0])

        ts = ts_end

print(f"✔ Dataset generated: {OUT}")

# ================= PERIOD SUMMARY =================
def detect_formula(rows):
    rts_exports = [r["export_kwh"] for r in rows if r["meter_serial"].startswith("SOLAR")]
    bess_exports = [r["export_kwh"] for r in rows if r["meter_serial"].startswith("BESS")]

    self_ok = any(r["meter_serial"] == "SELF_01" and r["import_kwh"] > 0 for r in rows)
    grid_ok = any(r["meter_serial"] == "GRID_01" and r["export_kwh"] > 0 for r in rows)
    inter_ok = any(r["meter_serial"] == "DEST_01" and r["import_kwh"] > 0 for r in rows)

    all_rts_ok = all(v > 0 for v in rts_exports)
    all_bess_ok = all(v > 0 for v in bess_exports)

    if all_rts_ok and all_bess_ok and self_ok and grid_ok and inter_ok:
        return "F01_NORMAL"
    if not self_ok and all_rts_ok and all_bess_ok and grid_ok and inter_ok:
        return "F05_NO_SELF"
    if all_rts_ok and not all_bess_ok and self_ok and grid_ok and inter_ok:
        return "F06_ONLY_BESS_FAULTY"
    if not all_rts_ok and all_bess_ok and self_ok and grid_ok and inter_ok:
        return "F04_ONLY_RTS_FAULTY"
    if all_rts_ok and all_bess_ok and self_ok and not grid_ok and inter_ok:
        return "F02_NO_GRID"
    if all_rts_ok and all_bess_ok and self_ok and grid_ok and not inter_ok:
        return "F03_NO_INTERCONNECT"
    if not all_rts_ok and not all_bess_ok and self_ok and grid_ok and inter_ok:
        return "F07_BOTH_BESS_RTS_FAULTY"
    return "UNCLASSIFIED"

# Group by interval
intervals = defaultdict(list)
with open(OUT, newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        key = (row["ts_start"], row["ts_end"])
        intervals[key].append({
            "meter_serial": row["meter_serial"],
            "import_kwh": float(row["import_kwh"]),
            "export_kwh": float(row["export_kwh"]),
        })

# Build timeline
timeline = []
for (ts_s, ts_e), rows in intervals.items():
    timeline.append((
        datetime.fromisoformat(ts_s),
        datetime.fromisoformat(ts_e),
        detect_formula(rows)
    ))
timeline.sort(key=lambda x: x[0])

# Merge contiguous periods
periods = defaultdict(list)
cur_start, cur_end, cur_code = timeline[0]
for s, e, code in timeline[1:]:
    if code == cur_code and s == cur_end:
        cur_end = e
    else:
        periods[cur_code].append((cur_start, cur_end))
        cur_start, cur_end, cur_code = s, e, code
periods[cur_code].append((cur_start, cur_end))

print("\n=== PERIOD SUMMARY ===")
for code in sorted(periods):
    print(f"\n{code}:")
    for s, e in periods[code]:
        print(f"  {s.isoformat()}  ->  {e.isoformat()}")
