from fastapi import APIRouter, Query, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from model.models import ScenarioWindow, MeterStatusSummary, Meter
from pydantic import BaseModel

router = APIRouter()


# ========== RESPONSE SCHEMAS ==========

class FaultInfo(BaseModel):
    meter_id: int
    meter_serial: str
    meter_name: Optional[str] = None
    fault_start_ts: datetime
    fault_end_ts: Optional[datetime]


class ScenarioWindowInfo(BaseModel):
    id: str
    scenario_code: str
    window_start_ts: datetime
    window_end_ts: Optional[datetime]
    faults: List[FaultInfo]


# ========== MODE 1: QUERY FAULTS BY MONTH ==========

@router.get("/faults/by-month", response_model=List[ScenarioWindowInfo])
def get_faults_by_month(
    request: Request,
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
):
    engine = request.app.state.engine
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)

    with Session(engine) as session:
        windows = (
            session.query(ScenarioWindow)
            .filter(
                ScenarioWindow.window_start_ts >= start,
                ScenarioWindow.window_start_ts < end,
            )
            .order_by(ScenarioWindow.window_start_ts)
            .all()
        )

        result = []

        for w in windows:
            faults = (
                session.query(MeterStatusSummary, Meter)
                .join(Meter, Meter.id == MeterStatusSummary.meter_id)
                .filter(MeterStatusSummary.source_period_id == w.id)
                .all()
            )

            result.append(ScenarioWindowInfo(
                id=str(w.id),
                scenario_code=w.scenario_code,
                window_start_ts=w.window_start_ts,
                window_end_ts=w.window_end_ts,
                faults=[
                    FaultInfo(
                        meter_id=m.id,
                        meter_serial=str(m.serial_number),
                        meter_name=m.meter_name,
                        fault_start_ts=s.fault_start_ts,
                        fault_end_ts=s.fault_end_ts,
                    )
                    for s, m in faults
                ]
            ))

        return result


# ========== MODE 2: QUERY FAULTS BY WINDOW TIMESTAMP RANGE ==========

@router.get("/faults/by-window", response_model=ScenarioWindowInfo)
def get_faults_by_window_time(
    request: Request,
    window_start_ts: datetime = Query(..., description="Start datetime of the scenario window"),
    window_end_ts: datetime = Query(..., description="End datetime of the scenario window"),
):
    engine = request.app.state.engine

    with Session(engine) as session:
        window = (
            session.query(ScenarioWindow)
            .filter(
                ScenarioWindow.window_start_ts == window_start_ts,
                ScenarioWindow.window_end_ts == window_end_ts,
            )
            .first()
        )

        if not window:
            raise HTTPException(status_code=404, detail="Scenario window not found")

        faults = (
            session.query(MeterStatusSummary, Meter)
            .join(Meter, Meter.id == MeterStatusSummary.meter_id)
            .filter(MeterStatusSummary.source_period_id == window.id)
            .all()
        )

        return ScenarioWindowInfo(
            id=str(window.id),
            scenario_code=window.scenario_code,
            window_start_ts=window.window_start_ts,
            window_end_ts=window.window_end_ts,
            faults=[
                FaultInfo(
                    meter_id=m.id,
                    meter_serial=str(m.serial_number),
                    meter_name=m.meter_name,
                    fault_start_ts=s.fault_start_ts,
                    fault_end_ts=s.fault_end_ts,
                )
                for s, m in faults
            ]
        )
