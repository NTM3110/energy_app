from model.models import IntervalState, MeterReading, Meter, ProfileReadingValue
from app.scenario import detect_scenario
from datetime import timedelta

INTERVAL_DURATION = timedelta(minutes=30)

EXPECTED_BESS_SOURCES = 4
EXPECTED_RFS_SOURCES = 4


def build_interval_state(db, ts):
    bess_meters = db.query(Meter).filter_by(source_id=1).all()
    rfs_meters = db.query(Meter).filter_by(source_id=2).all()
    self_meter = db.query(Meter).filter_by(role_id=2).first()
    grid_meter = db.query(Meter).filter_by(role_id=3).first()
    inter_meter = db.query(Meter).filter_by(role_id=4).first()

    readings = (
        db.query(MeterReading, Meter)
        .join(Meter)
        .filter(
            MeterReading.time_stamp == ts,
            )
        .all()
    )

    bess_count = 0
    rfs_count = 0
    self_present = False
    grid_present = False
    inter_present = False

    for r, m in readings:
        if m.role_id == 1 and m.source_id == 1 and r.total_energy_tot_exp_wh > 0.0:
            bess_count += 1
        elif m.role_id == 1 and m.source_id == 2 and r.total_energy_tot_exp_wh > 0.0:
            rfs_count += 1
        elif m.role_id == 2 and r.total_energy_tot_imp_wh > 0.0:
            self_present = True
        elif m.role_id == 3 and r.total_energy_tot_exp_wh > 0.0:
            grid_present = True
        elif m.role_id == 4 and r.total_energy_tot_imp_wh > 0.0:
            inter_present = True

    bess_available = bess_count > 0
    rfs_available = rfs_count > 0

    bess_missing_count = (len(bess_meters) - bess_count) if bess_available else len(bess_meters)
    rfs_missing_count = (len(rfs_meters) - rfs_count) if rfs_available else len(rfs_meters)

    # clamp to sane bounds
    bess_missing_count = max(0, min(bess_missing_count, len(bess_meters)))
    rfs_missing_count = max(0, min(rfs_missing_count, len(rfs_meters)))

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
