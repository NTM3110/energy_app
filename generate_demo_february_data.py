from datetime import datetime, timedelta
import csv
import random

START = datetime(2026, 2, 1, 0, 0, 0)
END = datetime(2026, 3, 1, 0, 0, 0)

INTERVAL = timedelta(minutes=30)

# Energy per 30 minutes (kWh)
BESS_RANGE = (0.20, 0.40)
SOLAR_RANGE = (0.10, 0.30)
EXPORT_SHARE_RANGE = (0.60, 0.95)
LOSS_RATE_RANGE = (0.005, 0.03)

OUT = "demo_data_february.csv"


def in_range(ts, start, end):
    return start <= ts < end


with open(OUT, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow([
        "meter_serial",
        "ts_start",
        "ts_end",
        "import_kwh",
        "export_kwh",
    ])

    ts = START

    while ts < END:
        ts_end = ts + INTERVAL

        # ---- failure windows ----
        lose_bess = in_range(ts,
            datetime(2026, 2, 5, 10, 0),
            datetime(2026, 2, 5, 12, 0)
        )

        lose_rfs = in_range(ts,
            datetime(2026, 2, 12, 14, 0),
            datetime(2026, 2, 12, 15, 30)
        )

        lose_grid = in_range(ts,
            datetime(2026, 2, 18, 8, 0),
            datetime(2026, 2, 18, 9, 0)
        )

        lose_both_sources = in_range(ts,
            datetime(2026, 2, 25, 20, 0),
            datetime(2026, 2, 25, 21, 0)
        )

        # ---- generation ----
        bess = 0.0 if (lose_bess or lose_both_sources) else round(random.uniform(*BESS_RANGE), 4)
        solar = 0.0 if (lose_rfs or lose_both_sources) else round(random.uniform(*SOLAR_RANGE), 4)

        total_gen = bess + solar

        export = 0.0
        self_use = 0.0
        dest_import = 0.0

        if total_gen > 0:
            export_share = random.uniform(*EXPORT_SHARE_RANGE)
            export = round(total_gen * export_share, 4)
            self_use = round(total_gen - export, 4)

            if not lose_grid:
                loss_rate = random.uniform(*LOSS_RATE_RANGE)
                dest_import = round(export * (1.0 - loss_rate), 4)

        # ---- write meters ----

        if bess > 0:
            writer.writerow(["BESS_01", ts.isoformat(), ts_end.isoformat(), 0, bess])

        if solar > 0:
            writer.writerow(["SOLAR_01", ts.isoformat(), ts_end.isoformat(), 0, solar])

        writer.writerow(["SELF_01", ts.isoformat(), ts_end.isoformat(), self_use, 0])

        if not lose_grid:
            writer.writerow(["GRID_01", ts.isoformat(), ts_end.isoformat(), 0, export])

        writer.writerow(["DEST_01", ts.isoformat(), ts_end.isoformat(), dest_import, 0])

        ts = ts_end


print(
    f"Generated {OUT}\n"
    f"- Interval: 30 minutes\n"
    f"- February 2026\n"
    f"- Includes intentional meter-loss scenarios"
)
