# app/period_builder.py
from model.models import IntervalState, CalculationPeriod
from app.scenario import formula_for_interval_state
from sqlalchemy import func


# app/period_builder.py
from model.models import IntervalState, CalculationPeriod
from app.scenario import formula_for_interval_state
from sqlalchemy import func
from datetime import timedelta

INTERVAL_DURATION = timedelta(minutes=30)


def build_periods(db, year, month):
    # ------------------------------------------------
    # 1. Determine data-driven cutoff (CSV time)
    # ------------------------------------------------
    cutoff = (
        db.query(func.max(IntervalState.ts))
        .filter(
            IntervalState.year == year,
            IntervalState.month == month,
        )
        .scalar()
    )

    if cutoff is None:
        return

    # ------------------------------------------------
    # 2. Delete existing periods for this month
    #    (periods are derived, rebuildable)
    # ------------------------------------------------
    db.query(CalculationPeriod).filter_by(
        year=year,
        month=month
    ).delete()
    db.commit()

    # ------------------------------------------------
    # 3. Load interval states IN TIME ORDER, UP TO CUTOFF
    # ------------------------------------------------
    intervals = (
        db.query(IntervalState)
        .filter(
            IntervalState.year == year,
            IntervalState.month == month,
            IntervalState.ts <= cutoff,   # 🔑 critical for stream mode
        )
        .order_by(IntervalState.ts)
        .all()
    )

    current = None

    for i in intervals:
        # Determine FINAL billing formula for this interval
        formula_code = formula_for_interval_state(
            bess_missing_count=i.bess_missing_count,
            rfs_missing_count=i.rfs_missing_count,
            self_available=i.self_available,
            grid_available=i.grid_available,
            inter_available=i.interconnect_available,
        )
        ts_end = i.ts
        ts_start = ts_end - INTERVAL_DURATION

        if current is None:
            current = {
                "start": ts_start,
                "end": ts_end,
                "scenario": i.scenario_code,   # descriptive state
                "formula": formula_code,       # billing logic
                "count": 1,
            }
            continue

        # Merge only if BOTH scenario AND formula match
        if (
            i.scenario_code == current["scenario"]
            and formula_code == current["formula"]
        ):
            current["end"] = ts_end
            current["count"] += 1
        else:
            db.add(CalculationPeriod(
                period_start=current["start"],
                period_end=current["end"],
                year=year,
                month=month,
                scenario_code=current["scenario"],
                formula_code=current["formula"],
                interval_count=current["count"],
            ))

            current = {
                "start": ts_start,
                "end": ts_end,
                "scenario": i.scenario_code,
                "formula": formula_code,
                "count": 1,
            }

    # ------------------------------------------------
    # 4. Flush final open period
    # ------------------------------------------------
    if current:
        db.add(CalculationPeriod(
            period_start=current["start"],
            period_end=current["end"],
            year=year,
            month=month,
            scenario_code=current["scenario"],
            formula_code=current["formula"],
            interval_count=current["count"],
        ))

    db.commit()
