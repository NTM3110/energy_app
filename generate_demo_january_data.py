from datetime import datetime, timedelta
import csv
import random

START = datetime(2026, 1, 1, 0, 0, 0)
DAYS = 30

# ✅ 30-MINUTE INTERVAL
INTERVAL = timedelta(minutes=30)

# ⚡ Energy PER 30 MINUTES (kWh)
BESS_RANGE = (0.20, 0.40)
SOLAR_RANGE = (0.10, 0.30)

# Portion of generation exported
EXPORT_SHARE_RANGE = (0.60, 0.95)

# Grid loss
LOSS_RATE_RANGE = (0.005, 0.03)

out_path = "demo_data_month.csv"

with open(out_path, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow([
        "meter_serial",
        "ts_start",
        "ts_end",
        "import_kwh",
        "export_kwh",
    ])

    ts = START
    end_ts = START + timedelta(days=DAYS)

    while ts < end_ts:
        ts_end = ts + INTERVAL

        # 🔋 Source generation (30-min energy)
        bess = round(random.uniform(*BESS_RANGE), 4)
        solar = round(random.uniform(*SOLAR_RANGE), 4)
        total_gen = bess + solar

        # 🚚 Export vs self-use
        export_share = random.uniform(*EXPORT_SHARE_RANGE)
        export = round(total_gen * export_share, 4)
        self_use = round(total_gen - export, 4)

        # 📉 Transmission loss
        loss_rate = random.uniform(*LOSS_RATE_RANGE)
        dest_import = round(export * (1.0 - loss_rate), 4)

        # 🧾 Write ONE 30-minute interval (5 meters)
        writer.writerow(["BESS_01", ts.isoformat(), ts_end.isoformat(), 0, bess])
        writer.writerow(["SOLAR_01", ts.isoformat(), ts_end.isoformat(), 0, solar])
        writer.writerow(["SELF_01", ts.isoformat(), ts_end.isoformat(), self_use, 0])
        writer.writerow(["GRID_01", ts.isoformat(), ts_end.isoformat(), 0, export])
        writer.writerow(["DEST_01", ts.isoformat(), ts_end.isoformat(), dest_import, 0])

        ts = ts_end

print(
    f"Generated {out_path}\n"
    f"- Interval: 30 minutes\n"
    f"- Energy values: per 30 minutes\n"
    f"- Energy conserved: self_use + export = BESS + SOLAR"
)
