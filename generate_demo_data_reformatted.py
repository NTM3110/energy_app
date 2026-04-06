from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass
import csv
import random

# ============================================================
# CONFIG
# ============================================================
START = datetime(2025, 1, 1, 0, 0)
END   = datetime(2026, 5, 1, 0, 0)
INTERVAL = timedelta(minutes=30)

OUT = "reformatted_demo_lp_2025_01_to_26.csv"
random.seed(42)

# ============================================================
# METERS
# ============================================================
BESS  = [f"BESS_{i:02d}" for i in range(1, 5)]
RTS   = [f"SOLAR_{i:02d}" for i in range(1, 5)]
SELF  = "SELF_01"
GRID  = "GRID_01"
DEST  = "DEST_01"
ALL_METERS = BESS + RTS + [SELF, GRID, DEST]

# ============================================================
# ENERGY RANGES
# ============================================================
RANGE = {
    "BESS": (1.0, 3.0),
    "RTS":  (2.0, 6.0),
    "SELF": (1.0, 2.5),
}

# ============================================================
# FAULT EVENTS
# ============================================================
@dataclass(frozen=True)
class FaultEvent:
    start: datetime
    end: datetime
    meters: tuple[str, ...]

def snap_30(ts):
    return ts.replace(minute=(ts.minute // 30) * 30, second=0, microsecond=0)

def make_event(start, hours, meters):
    start = snap_30(start)
    end = snap_30(start + timedelta(hours=hours))
    return FaultEvent(start, end, tuple(meters))

FAULT_EVENTS = [
   
    make_event(datetime(2025, 1, 27, 6), 20, [GRID]),
    make_event(datetime(2025, 2, 28, 7), 12, [DEST]),
    make_event(datetime(2025, 2, 22, 8), 12, [random.choice(BESS)]),
    make_event(datetime(2025, 3, 22, 8), 12, [random.choice(BESS)]),
    make_event(datetime(2025, 4, 8, 9), 12, [SELF]), 
    make_event(datetime(2025, 12, 1, 5), 24, [random.choice(RTS)]),
    make_event(datetime(2026, 1, 10, 3), 6, [random.choice(BESS)]),
    make_event(datetime(2026, 1, 20, 11), 4, [random.choice(RTS)]),
    make_event(datetime(2026, 2, 5, 9), 5, [random.choice(BESS), random.choice(RTS)]),
    make_event(datetime(2026, 2, 18, 14), 3, [GRID]),
    make_event(datetime(2026, 3, 10, 8), 2, [DEST]),
    make_event(datetime(2026, 4, 9, 2), 6, [random.choice(BESS), random.choice(RTS)])
]

def active_fault(ts):
    for e in FAULT_EVENTS:
        if e.start <= ts < e.end:
            return set(e.meters)
    return set()

def random_k_factor(base=0.02, delta=0.0001):
    return round(random.uniform(base - delta, base + delta), 6)

def fmt_dt(dt):
    return dt.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

# ============================================================
# GENERATE CUMULATIVE LP CSV
# ============================================================
cumulative_energy = {
    meter: {"import": 0.0, "export": 0.0}
    for meter in ALL_METERS
}

# Define reformatted fieldnames
FIELDNAMES = [
    "meter_id", 
    "time_stamp", 
    "record_status", 
    "total_energy_tot_imp_wh", 
    "total_energy_tot_exp_wh", 
    "total_energy_tot_imp_va", 
    "total_energy_tot_exp_va"
]

rows = []
ts = START

while ts < END:
    faulty = active_fault(ts)
    ts_out = fmt_dt(ts + INTERVAL)

    bess_true = {m: random.uniform(*RANGE["BESS"]) for m in BESS}
    rts_true  = {m: random.uniform(*RANGE["RTS"])  for m in RTS}

    true_total_source = sum(bess_true.values()) + sum(rts_true.values())

    bess_measured = {m: 0.0 if m in faulty else bess_true[m] for m in BESS}
    rts_measured  = {m: 0.0 if m in faulty else rts_true[m] for m in RTS}

    self_import = 0.0 if SELF in faulty else min(random.uniform(*RANGE["SELF"]), true_total_source)
    grid_export = 0.0 if GRID in faulty else max(true_total_source - self_import, 0.0)
    k = random_k_factor()

    dest_import = 0.0 if DEST in faulty else round((true_total_source - self_import) * (1 - k), 3)

    for m in BESS:
        if m in faulty: continue
        cumulative_energy[m]["export"] += bess_measured[m]
        rows.append({
            "meter_id": m, "time_stamp": ts_out, "record_status": 0,
            "total_energy_tot_imp_wh": 0.0, "total_energy_tot_exp_wh": round(cumulative_energy[m]["export"], 3),
            "total_energy_tot_imp_va": 0, "total_energy_tot_exp_va": 0
        })

    for m in RTS:
        if m in faulty: continue
        cumulative_energy[m]["export"] += rts_measured[m]
        rows.append({
            "meter_id": m, "time_stamp": ts_out, "record_status": 0,
            "total_energy_tot_imp_wh": 0.0, "total_energy_tot_exp_wh": round(cumulative_energy[m]["export"], 3),
            "total_energy_tot_imp_va": 0, "total_energy_tot_exp_va": 0
        })

    if SELF not in faulty:
        cumulative_energy[SELF]["import"] += self_import
        rows.append({
            "meter_id": SELF, "time_stamp": ts_out, "record_status": 0,
            "total_energy_tot_imp_wh": round(cumulative_energy[SELF]["import"], 3), "total_energy_tot_exp_wh": 0.0,
            "total_energy_tot_imp_va": 0, "total_energy_tot_exp_va": 0
        })

    if GRID not in faulty:
        cumulative_energy[GRID]["export"] += grid_export
        rows.append({
            "meter_id": GRID, "time_stamp": ts_out, "record_status": 0,
            "total_energy_tot_imp_wh": 0.0, "total_energy_tot_exp_wh": round(cumulative_energy[GRID]["export"], 3),
            "total_energy_tot_imp_va": 0, "total_energy_tot_exp_va": 0
        })

    if DEST not in faulty:
        cumulative_energy[DEST]["import"] += dest_import
        rows.append({
            "meter_id": DEST, "time_stamp": ts_out, "record_status": 0,
            "total_energy_tot_imp_wh": round(cumulative_energy[DEST]["import"], 3), "total_energy_tot_exp_wh": 0.0,
            "total_energy_tot_imp_va": 0, "total_energy_tot_exp_va": 0
        })

    ts += INTERVAL

with open(OUT, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
    writer.writeheader()
    writer.writerows(rows)

print(f"✔ Reformatted LP CSV generated: {OUT}")

# ============================================================
# PERIOD SUMMARY (Updated to use new field names)
# ============================================================
def detect_formula(rows):
    bess = [r["total_energy_tot_exp_wh"] for r in rows if r["meter_id"].startswith("BESS")]
    rts  = [r["total_energy_tot_exp_wh"] for r in rows if r["meter_id"].startswith("SOLAR")]

    self_ok  = any(r["meter_id"] == SELF and r["total_energy_tot_imp_wh"] > 0 for r in rows)
    grid_ok  = any(r["meter_id"] == GRID and r["total_energy_tot_exp_wh"] > 0 for r in rows)
    inter_ok = any(r["meter_id"] == DEST and r["total_energy_tot_imp_wh"] > 0 for r in rows)

    all_bess_ok = len(bess) == 4 and all(v > 0 for v in bess)
    all_rts_ok  = len(rts)  == 4 and all(v > 0 for v in rts)

    if all_bess_ok and all_rts_ok and self_ok and grid_ok and inter_ok:
        return "F01_NORMAL"
    if all_bess_ok and all_rts_ok and self_ok and not grid_ok:
        return "F02_NO_GRID"
    if all_bess_ok and all_rts_ok and self_ok and not inter_ok:
        return "F03_NO_INTERCONNECT"
    if not all_rts_ok and all_bess_ok:
        return "F04_ONLY_RTS_FAULTY"
    if not self_ok and grid_ok and inter_ok:
        return "F05_ONLY_SELF_FAULTY"
    if all_rts_ok and not all_bess_ok:
        return "F06_ONLY_BESS_FAULTY"
    if not all_rts_ok and not all_bess_ok:
        return "F07_BOTH_BESS_RTS_FAULTY"

    return "UNCLASSIFIED"

intervals = defaultdict(list)

with open(OUT, newline="") as f:
    for r in csv.DictReader(f):
        ts = datetime.strptime(r["time_stamp"], "%Y-%m-%d %H:%M:%S")
        intervals[ts].append({
            "meter_id": r["meter_id"],
            "total_energy_tot_imp_wh": float(r["total_energy_tot_imp_wh"]),
            "total_energy_tot_exp_wh": float(r["total_energy_tot_exp_wh"]),
        })

timeline = [(ts, detect_formula(rows)) for ts, rows in sorted(intervals.items())]

print("\n=== PERIOD SUMMARY (TIME ORDERED) ===")
if timeline:
    cur_ts, cur_code = timeline[0]
    prev_ts = cur_ts

    for ts, code in timeline[1:]:
        if ts == prev_ts + INTERVAL and code == cur_code:
            prev_ts = ts
        else:
            print(f"{cur_ts} -> {prev_ts}  {cur_code}")
            cur_ts, prev_ts, cur_code = ts, ts, code
    print(f"{cur_ts} -> {prev_ts}  {cur_code}")