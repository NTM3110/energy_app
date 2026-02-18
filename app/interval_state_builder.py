from model.models import IntervalState, MeterReading, Meter
from app.scenario import detect_scenario
from datetime import timedelta

INTERVAL_DURATION = timedelta(minutes=30)

EXPECTED_BESS_SOURCES = 4
EXPECTED_RFS_SOURCES = 4


def build_interval_state(db, ts):
    readings = (
        db.query(MeterReading, Meter)
        .join(Meter)
        .filter(
            MeterReading.ts == ts,
            )
        .all()
    )

    bess_count = 0
    rfs_count = 0
    self_present = False
    grid_present = False
    inter_present = False

    for r, m in readings:
        if m.role == "SOURCE" and m.source_id == 1 and r.export_kwh > 0.0:
            bess_count += 1
        elif m.role == "SOURCE" and m.source_id == 2 and r.export_kwh > 0.0:
            rfs_count += 1
        elif m.role == "SELF_USE" and r.import_kwh > 0.0:
            self_present = True
        elif m.role == "GRID_POINT" and r.export_kwh > 0.0:
            grid_present = True
        elif m.role == "INTERCONNECT" and r.import_kwh > 0.0:
            inter_present = True

    bess_available = bess_count > 0
    rfs_available = rfs_count > 0

    bess_missing_count = (EXPECTED_BESS_SOURCES - bess_count) if bess_available else EXPECTED_BESS_SOURCES
    rfs_missing_count = (EXPECTED_RFS_SOURCES - rfs_count) if rfs_available else EXPECTED_RFS_SOURCES

    # clamp to sane bounds
    bess_missing_count = max(0, min(bess_missing_count, EXPECTED_BESS_SOURCES))
    rfs_missing_count = max(0, min(rfs_missing_count, EXPECTED_RFS_SOURCES))

    scenario = detect_scenario(
        bess_missing_count=bess_missing_count,
        rfs_missing_count=rfs_missing_count,
        self_available=self_present,
        grid_available=grid_present,
        inter_available=inter_present,
    )

    state = IntervalState(
        ts=ts,
        year=(ts-INTERVAL_DURATION).year,
        month=(ts-INTERVAL_DURATION).month,

        self_available=self_present,
        grid_available=grid_present,
        interconnect_available=inter_present,

        bess_available=bess_available,
        rfs_available=rfs_available,
        bess_missing_count=bess_missing_count,
        rfs_missing_count=rfs_missing_count,

        scenario_code=scenario,
    )

    db.merge(state)
    db.commit()
