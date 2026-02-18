from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException, Query, Depends, Response
from sqlalchemy.orm import Session
from sqlalchemy import extract, asc, desc, text
from typing import Optional
from io import StringIO
import csv
# Import your ORM models for these tables.
# If you don't have them yet, add them in model/models.py first.
from model.models import MonthlyEnergySummary, MonthlyCalculationBreakdown

router = APIRouter()

SORTABLE_COLUMNS = {
    "interval_count": MonthlyCalculationBreakdown.interval_count,
    "rts_energy_kwh": MonthlyCalculationBreakdown.rts_energy_kwh,
    "bess_energy_kwh": MonthlyCalculationBreakdown.bess_energy_kwh,
    "self_use_energy_kwh": MonthlyCalculationBreakdown.self_use_energy_kwh,
    "grid_energy_kwh": MonthlyCalculationBreakdown.grid_energy_kwh,
    "interconnect_energy": MonthlyCalculationBreakdown.interconnect_energy_kwh,
    "k_factor": MonthlyCalculationBreakdown.k_factor,
    "rts_to_lmv_kwh": MonthlyCalculationBreakdown.rts_to_lmv_kwh,
    "bess_to_lmv_kwh": MonthlyCalculationBreakdown.bess_to_lmv_kwh,
}

@router.get("/energy/monthly-summary")
def get_monthly_summary(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    engine = request.app.state.engine
    with Session(engine) as session:
        q = session.query(MonthlyEnergySummary)

        if year is not None:
            q = q.filter(MonthlyEnergySummary.year == year)
        if month is not None:
            q = q.filter(MonthlyEnergySummary.month == month)

        total = q.count()

        items = (
            q.order_by(MonthlyEnergySummary.year.desc(), MonthlyEnergySummary.month.desc())
             .limit(limit)
             .offset(offset)
             .all()
        )

    return {
        "items": [i.__dict__ for i in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/energy/monthly-breakdown")
def get_monthly_breakdown(
    request: Request,
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    scenario_code: str | None = None,
    formula_code: str | None = None,
    sort_by: str | None = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    engine = request.app.state.engine
    with Session(engine) as session:
        q = session.query(MonthlyCalculationBreakdown)

        # filter by month via period_start
        q = q.filter(extract("year", MonthlyCalculationBreakdown.period_start) == year)
        q = q.filter(extract("month", MonthlyCalculationBreakdown.period_start) == month)

        if scenario_code:
            q = q.filter(MonthlyCalculationBreakdown.scenario_code == scenario_code)

        if formula_code:
            q = q.filter(MonthlyCalculationBreakdown.formula_code == formula_code)

        total = q.count()

        # ORDER BY strategy:
        # - default: period_start, period_end
        # - if sort_by: sort_by first, then period_start, period_end
        if sort_by is not None:
            col = SORTABLE_COLUMNS.get(sort_by)
            if col is None:
                raise HTTPException(400, f"Invalid sort_by: {sort_by}")

            primary = asc(col) if sort_dir == "asc" else desc(col)
            q = q.order_by(
                primary,
                asc(MonthlyCalculationBreakdown.period_start),
                asc(MonthlyCalculationBreakdown.period_end),
            )
        else:
            q = q.order_by(
                asc(MonthlyCalculationBreakdown.period_start),
                asc(MonthlyCalculationBreakdown.period_end),
            )

        items = q.limit(limit).offset(offset).all()

    # If you don't want __dict__ leaking SQLAlchemy internals,
    # switch to Pydantic schemas later. For now this is quick.
    return {
        "items": [i.__dict__ for i in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }



@router.get("/energy/interval-raw/csv")
def get_interval_raw_csv(
    request: Request,
    from_ts: Optional[str] = Query(None, description="ISO datetime, inclusive"),
    to_ts: Optional[str] = Query(None, description="ISO datetime, exclusive"),
):
    engine = request.app.state.engine

    base_sql = """
        SELECT
            mr.ts,

            -- BESS
            SUM(mr.import_kwh) FILTER (WHERE m.serial_number = 'BESS_01') AS bess_1_import,
            SUM(mr.import_kwh) FILTER (WHERE m.serial_number = 'BESS_02') AS bess_2_import,
            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'BESS_01') AS bess_1_export,
            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'BESS_02') AS bess_2_export,
            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'BESS_03') AS bess_3_export,
            SUM(mr.import_kwh) FILTER (WHERE m.serial_number = 'BESS_03') AS bess_3_import,
            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'BESS_04') AS bess_4_export,
            SUM(mr.import_kwh) FILTER (WHERE m.serial_number = 'BESS_04') AS bess_4_import,
            -- RTS / SOLAR
            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'SOLAR_01') AS rts_1_export,
            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'SOLAR_02') AS rts_2_export,
            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'SOLAR_03') AS rts_3_export,
            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'SOLAR_04') AS rts_4_export,

            -- OTHER
            SUM(mr.import_kwh) FILTER (WHERE m.role = 'SELF_USE') AS self_import,
            SUM(mr.export_kwh) FILTER (WHERE m.role = 'GRID_POINT') AS grid_export,
            SUM(mr.import_kwh) FILTER (WHERE m.role = 'INTERCONNECT') AS interconnect_import

        FROM meter_reading mr
        JOIN meter m ON m.id = mr.meter_id
    """

    where_clauses = []
    params = {}

    if from_ts:
        where_clauses.append("mr.ts > :from_ts")
        params["from_ts"] = from_ts

    if to_ts:
        where_clauses.append("mr.ts <= :to_ts")
        params["to_ts"] = to_ts

    if where_clauses:
        base_sql += " WHERE " + " AND ".join(where_clauses)

    base_sql += """
        GROUP BY mr.ts
        ORDER BY mr.ts
    """

    with Session(engine) as session:
        rows = session.execute(text(base_sql), params).mappings().all()

    # Build CSV
    output = StringIO()
    writer = csv.writer(output)

    header = [
        "ts",
        "bess_1_import",
        "bess_2_import",
        "bess_3_import",
        "bess_4_import",
        "bess_1_export",
        "bess_2_export",
        "bess_3_export",
        "bess_4_export",
        "rts_1_export",
        "rts_2_export",
        "rts_3_export",
        "rts_4_export",
        "self_import",
        "grid_export",
        "interconnect_import",
    ]

    writer.writerow(header)

    def fmt_dt(dt):
        if dt is None:
            return ""
        val = dt.isoformat(sep=" ")
        return f'="{val}"'



    for r in rows:
        writer.writerow([
            fmt_dt(r.get("ts")),
            r.get("bess_1_import"),
            r.get("bess_2_import"),
            r.get("bess_3_import"),
            r.get("bess_4_import"),
            r.get("bess_1_export"),
            r.get("bess_2_export"),
            r.get("bess_3_export"),
            r.get("bess_4_export"),
            r.get("rts_1_export"),
            r.get("rts_2_export"),
            r.get("rts_3_export"),
            r.get("rts_4_export"),
            r.get("self_import"),
            r.get("grid_export"),
            r.get("interconnect_import"),
        ])


    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=interval_raw_energy.csv"
        },
    )

@router.get("/energy/interval-raw")
def get_interval_raw_json(
    request: Request,
    from_ts: Optional[str] = Query(None, description="ISO datetime, inclusive"),
    to_ts: Optional[str] = Query(None, description="ISO datetime, exclusive"),
):
    engine = request.app.state.engine

    base_sql = """
        SELECT
            mr.ts,

            -- BESS
            SUM(mr.import_kwh) FILTER (WHERE m.serial_number = 'BESS_01') AS bess_1_import,
            SUM(mr.import_kwh) FILTER (WHERE m.serial_number = 'BESS_02') AS bess_2_import,
            SUM(mr.import_kwh) FILTER (WHERE m.serial_number = 'BESS_03') AS bess_3_import,
            SUM(mr.import_kwh) FILTER (WHERE m.serial_number = 'BESS_04') AS bess_4_import,

            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'BESS_01') AS bess_1_export,
            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'BESS_02') AS bess_2_export,
            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'BESS_03') AS bess_3_export,
            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'BESS_04') AS bess_4_export,

            -- RTS / SOLAR
            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'SOLAR_01') AS rts_1_export,
            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'SOLAR_02') AS rts_2_export,
            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'SOLAR_03') AS rts_3_export,
            SUM(mr.export_kwh) FILTER (WHERE m.serial_number = 'SOLAR_04') AS rts_4_export,

            -- OTHER
            SUM(mr.import_kwh) FILTER (WHERE m.role = 'SELF_USE') AS self_import,
            SUM(mr.export_kwh) FILTER (WHERE m.role = 'GRID_POINT') AS grid_export,
            SUM(mr.import_kwh) FILTER (WHERE m.role = 'INTERCONNECT') AS interconnect_import

        FROM meter_reading mr
        JOIN meter m ON m.id = mr.meter_id
    """

    where_clauses = []
    params = {}

    if from_ts:
        where_clauses.append("mr.ts > :from_ts")
        params["from_ts"] = from_ts

    if to_ts:
        where_clauses.append("mr.ts <= :to_ts")
        params["to_ts"] = to_ts

    if where_clauses:
        base_sql += " WHERE " + " AND ".join(where_clauses)

    base_sql += """
        GROUP BY mr.ts
        ORDER BY mr.ts
    """

    with Session(engine) as session:
        rows = session.execute(text(base_sql), params).mappings().all()

    def fmt_dt(dt: Optional[datetime]):
        return dt.isoformat() if dt else None

    columns = [
        "ts",
        "bess_1_import",
        "bess_2_import",
        "bess_3_import",
        "bess_4_import",
        "bess_1_export",
        "bess_2_export",
        "bess_3_export",
        "bess_4_export",
        "rts_1_export",
        "rts_2_export",
        "rts_3_export",
        "rts_4_export",
        "self_import",
        "grid_export",
        "interconnect_import",
    ]

    data = []
    for r in rows:
        data.append({
            "ts": fmt_dt(r["ts"]),
            "bess_1_import": r["bess_1_import"],
            "bess_2_import": r["bess_2_import"],
            "bess_3_import": r["bess_3_import"],
            "bess_4_import": r["bess_4_import"],
            "bess_1_export": r["bess_1_export"],
            "bess_2_export": r["bess_2_export"],
            "bess_3_export": r["bess_3_export"],
            "bess_4_export": r["bess_4_export"],
            "rts_1_export": r["rts_1_export"],
            "rts_2_export": r["rts_2_export"],
            "rts_3_export": r["rts_3_export"],
            "rts_4_export": r["rts_4_export"],
            "self_import": r["self_import"],
            "grid_export": r["grid_export"],
            "interconnect_import": r["interconnect_import"],
        })

    return {
        "columns": columns,
        "rows": data,
        "meta": {
            "from_ts": from_ts,
            "to_ts": to_ts,
            "row_count": len(data),
        },
    }