import uuid
from collections import defaultdict
from sqlalchemy import and_
from model.models import (
    MeterReading,
    CalculationPeriod,
    MeterStatusSummary,
    ScenarioWindow,
    Meter
)
from datetime import timedelta

INTERVAL_DURATION = timedelta(minutes=30)

# ============================================================
# CONFIG
# ============================================================

# ============================================================
# FAULT RULE
# ============================================================

def is_faulty_reading(reading: MeterReading) -> bool:
    return reading.total_energy_tot_exp_wh == 0 and reading.total_energy_tot_imp_wh == 0


# ============================================================
# SCENARIO WINDOW
# ============================================================

def get_or_create_scenario_window(session, period: CalculationPeriod):

    window = (
        session.query(ScenarioWindow)
        .filter(
            ScenarioWindow.scenario_code == period.scenario_code,
            ScenarioWindow.window_end_ts.is_(None),
        )
        .one_or_none()
    )

    if window:
        return window

    # Scenario changed → close open windows
    open_windows = (
        session.query(ScenarioWindow)
        .filter(ScenarioWindow.window_end_ts.is_(None))
        .all()
    )

    for w in open_windows:
        w.window_end_ts = period.period_start

        # 🔴 CLOSE ALL FAULTS BELONGING TO THIS WINDOW
        session.query(MeterStatusSummary).filter(
            MeterStatusSummary.source_period_id == w.id,
            MeterStatusSummary.is_open.is_(True),
        ).update(
            {
                "fault_end_ts": w.window_end_ts,
                "is_open": False,
            }
        )

    # Open new window
    window = ScenarioWindow(
        scenario_code=period.scenario_code,
        window_start_ts=period.period_start,
        window_end_ts=None,
    )

    session.add(window)
    session.flush()

    return window


# ============================================================
# PROCESS PERIOD (HYBRID, FINAL)
# ============================================================

def process_period(session, period: CalculationPeriod):
    """
    Improved fault detection:
    - Fault = zero reading OR missing meter reading
    - Uses ScenarioWindow for tracking
    """
    scenario_window = get_or_create_scenario_window(session, period)

    if period.scenario_code == "ALL_OK":
        return

    # All meters in the system
    all_meters = {
        m.id: m.serial_number for m in session.query(Meter).all()
    }

    # Pull readings for this period
    readings = (
        session.query(MeterReading)
        .filter(
            MeterReading.time_stamp > period.period_start,
            MeterReading.time_stamp <= period.period_end,
        )
        .all()
    )

    # Group readings by meter_id
    readings_by_meter = defaultdict(list)
    for r in readings:
        readings_by_meter[r.meter_id].append(r)

    # 🔄 New: Include missing meters as faults
    for meter_id in all_meters:
        meter_readings = readings_by_meter.get(meter_id, [])

        # Check if a fault is already open
        open_fault = (
            session.query(MeterStatusSummary)
            .filter(
                MeterStatusSummary.meter_id == meter_id,
                MeterStatusSummary.source_period_id == scenario_window.id,
                MeterStatusSummary.is_open.is_(True),
            )
            .one_or_none()
        )

        if not meter_readings:
            # Entirely missing meter = faulted interval
            if open_fault is None:
                session.add(MeterStatusSummary(
                    meter_id=meter_id,
                    fault_start_ts=period.period_start,
                    fault_end_ts=None,
                    is_open=True,
                    source_period_id=scenario_window.id,
                ))
        else:
            for r in meter_readings:
                faulty = is_faulty_reading(r)

                # ----- Open Fault -----
                if faulty and open_fault is None:
                    open_fault = MeterStatusSummary(
                        meter_id=meter_id,
                        fault_start_ts=r.ts - INTERVAL_DURATION,
                        fault_end_ts=None,
                        is_open=True,
                        source_period_id=scenario_window.id,
                    )
                    session.add(open_fault)

                # ----- Close Fault -----
                elif not faulty and open_fault is not None:
                    open_fault.fault_end_ts = r.ts - INTERVAL_DURATION
                    open_fault.is_open = False
                    open_fault = None

    # Final cleanup for ended windows
    if scenario_window.window_end_ts is not None:
        session.query(MeterStatusSummary).filter(
            MeterStatusSummary.source_period_id == scenario_window.id,
            MeterStatusSummary.is_open.is_(True),
        ).update(
            {
                "fault_end_ts": scenario_window.window_end_ts,
                "is_open": False,
            }
        )



# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def build_meter_status_summary(session, mode="stream"):

    if mode == "batch":
        session.query(MeterStatusSummary).delete()
        session.query(ScenarioWindow).delete()
        session.commit()

        periods = (
            session.query(CalculationPeriod)
            .order_by(CalculationPeriod.period_start)
            .all()
        )

        for period in periods:
            process_period(session, period)
            session.commit()

    elif mode == "stream":
        period = (
            session.query(CalculationPeriod)
            .order_by(CalculationPeriod.period_end.desc())
            .first()
        )

        if period:
            process_period(session, period)
            session.commit()

    else:
        raise ValueError("mode must be 'batch' or 'stream'")
