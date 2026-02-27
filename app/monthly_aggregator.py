# app/monthly_aggregator.py
from sqlalchemy import func

from model.models import (
    MonthlyEnergySummary,
    MonthlyCalculationBreakdown,
    MeterReading,
    Meter,
    CalculationPeriod,
    IntervalState,
)
from app.calculation_formula import PeriodInputs, apply_formula
import datetime

from datetime import timedelta

INTERVAL_DURATION = timedelta(minutes=30)


def get_meter_reading_at(db, ts: datetime, meter_id: int, field: str = "export") -> float:
    from model.models import MeterReading
    reading = (
        db.query(MeterReading)
        .filter(
            MeterReading.time_stamp <= ts,
            MeterReading.meter_id == meter_id,
        )
        .order_by(MeterReading.time_stamp.desc())
        .first()
    )
    if reading is None:
        return 0.0
    return (
        reading.total_energy_tot_exp_wh if field == "export"
        else reading.total_energy_tot_imp_wh
    )


def load_last_month_k(db, year: int, month: int) -> float:
    """
    Load K-factor from the PREVIOUS FULL MONTH.
    """
    if month == 1:
        prev_year = year - 1
        prev_month = 12
    else:
        prev_year = year
        prev_month = month - 1

    row = (
        db.query(MonthlyEnergySummary)
        .filter(
            MonthlyEnergySummary.year == prev_year,
            MonthlyEnergySummary.month == prev_month,
            MonthlyEnergySummary.k_factor > 0.0,
        )
        .first()
    )

    return float(row.k_factor) if row else 0.0



def build_monthly_summary(db, year, month):
    # ------------------------------------------------
    # 1. Determine data-driven cutoff
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
    # 2. Upsert monthly summary
    # ------------------------------------------------
    summary = (
        db.query(MonthlyEnergySummary)
        .filter_by(year=year, month=month)
        .first()
    )

    if not summary:
        summary = MonthlyEnergySummary(
            year=year,
            month=month
        )
        db.add(summary)
        db.commit()

    # ------------------------------------------------
    # 3. Clear existing breakdowns (rebuildable)
    # ------------------------------------------------
    db.query(MonthlyCalculationBreakdown).filter(
        MonthlyCalculationBreakdown.monthly_summary_id == summary.id
    ).delete()
    db.commit()

    # ------------------------------------------------
    # 4. Reset totals
    # ------------------------------------------------
    summary.bess_to_lmv_energy_kwh = 0.0
    summary.rfs_to_lmv_energy_kwh = 0.0
    summary.total_energy_to_lmv_kwh = 0.0
    summary.k_factor = 0.0
    summary.number_of_inqualified_intervals = 0
    db.commit()

    # ------------------------------------------------
    # 5. Load periods UP TO CUTOFF
    # ------------------------------------------------
    periods = (
        db.query(CalculationPeriod)
        .filter(
            CalculationPeriod.year == year,
            CalculationPeriod.month == month,
            CalculationPeriod.period_end <= cutoff,
        )
        .order_by(CalculationPeriod.period_start)
        .all()
    )

    last_K = load_last_month_k(db, year, month)
    EPS = 1e-9
    period_count = len(periods)
    sum_of_k_factors = 0.0
    # ------------------------------------------------
    # 6. Process each period (settlement logic)
    # ------------------------------------------------
    for p in periods:

        grid = inter = self_use = 0.0

        # 1. Get list of meter IDs by type
        rts_meters = db.query(Meter).filter_by(role_id=1, source_id=2).all()
        bess_meters = db.query(Meter).filter_by(role_id=1, source_id=1).all()
        self_use_meters = db.query(Meter).filter_by(role_id=2).all()
        grid_meters = db.query(Meter).filter_by(role_id=3).all()
        inter_meters = db.query(Meter).filter_by(role_id=4).all()

        # 2. Get cumulative delta per meter
        rts_energy = 0.0
        bess_dis_energy = 0.0
        bess_chg_energy = 0.0

        for m in rts_meters:
            start = get_meter_reading_at(db, p.period_start + INTERVAL_DURATION, m.id, "export")
            end = get_meter_reading_at(db, p.period_end, m.id, "export")
            delta_rts = max(0.0, end - start)
            rts_energy += delta_rts

        for m in bess_meters:
            start_dis = get_meter_reading_at(db, p.period_start + INTERVAL_DURATION, m.id, "export")
            end_dis   = get_meter_reading_at(db, p.period_end, m.id, "export")
            delta_dis = max(0.0, end_dis - start_dis)
            bess_dis_energy += delta_dis

           # Optional: also calculate BESS charging if needed
            start_chg = get_meter_reading_at(db, p.period_start + INTERVAL_DURATION, m.id, "import")
            end_chg   = get_meter_reading_at(db, p.period_end, m.id, "import")
            delta_chg = max(0.0, end_chg - start_chg)
            bess_chg_energy += delta_chg
        
        for m in self_use_meters:
            start = get_meter_reading_at(db, p.period_start + INTERVAL_DURATION, m.id, "import")
            end = get_meter_reading_at(db, p.period_end, m.id, "import")
            delta_self = max(0.0, end - start)
            self_use += delta_self

        for m in grid_meters:
            start = get_meter_reading_at(db, p.period_start + INTERVAL_DURATION, m.id, "export")
            end = get_meter_reading_at(db, p.period_end, m.id, "export")
            delta_grid = max(0.0, end - start)
            grid += delta_grid
        
        for m in inter_meters:
            start = get_meter_reading_at(db, p.period_start + INTERVAL_DURATION, m.id, "import")
            end = get_meter_reading_at(db, p.period_end, m.id, "import")
            delta_inter = max(0.0, end - start)
            inter += delta_inter

        inputs = PeriodInputs(
            E=grid if grid > 0 else None,
            E_LMV=inter if inter > 0 else None,
            E_self=self_use if self_use > 0 else None,
            RTS_exports=rts_energy,
            BESS_charge=bess_chg_energy,
            BESS_discharge=bess_dis_energy,
        )

        result = apply_formula(
            formula_code=p.formula_code,
            inputs=inputs,
            last_K=last_K,
        )

        if last_K == 0.0 and result.K and result.K > EPS:
            last_K = result.K

        if p.scenario_code == "INVALID":
            summary.number_of_inqualified_intervals += p.interval_count
        #     summary.quality_status = "INVALID"

        # ------------------------------------------------
        # 7. Store breakdown row
        # ------------------------------------------------
        db.add(MonthlyCalculationBreakdown(
            monthly_summary_id=summary.id,
            period_start=p.period_start,
            period_end=p.period_end,
            interval_count=p.interval_count,
            scenario_code=p.scenario_code,
            formula_code=p.formula_code,

            bess_energy_kwh=round(bess_dis_energy, 4),
            rts_energy_kwh=round(rts_energy, 4),
            self_use_energy_kwh=round(self_use, 4),
            grid_energy_kwh=round(grid, 4),
            interconnect_energy_kwh=round(inter, 4),

            k_factor=round(result.K, 6) if result.K is not None else None,
            rts_to_lmv_kwh=round(result.RTS_to_LMV, 4),
            bess_to_lmv_kwh=round(result.BESS_to_LMV, 4),
        ))

        # ------------------------------------------------
        # 8. Accumulate monthly totals
        # ------------------------------------------------
        summary.bess_to_lmv_energy_kwh += round(result.BESS_to_LMV, 4)
        summary.rfs_to_lmv_energy_kwh += round(result.RTS_to_LMV, 4)
        summary.total_energy_to_lmv_kwh += round(result.RTS_to_LMV + result.BESS_to_LMV, 4)
        sum_of_k_factors += last_K
        summary.start_date_time= periods[0].period_start
        summary.end_date_time= periods[-1].period_end

    summary.k_factor = round(sum_of_k_factors / period_count, 6) if period_count > 0 else 0.0
    db.commit()
