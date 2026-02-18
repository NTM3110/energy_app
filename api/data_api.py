import asyncio
import json
import time
from fastapi import APIRouter, Request, HTTPException
from driver.meters_config import USERNAME, PASWORD, SERIAL_NUMBER
from driver.edmi_enums import serialize_error, EDMI_ERROR_CODE
from utils.utils import format_list_registers
from db_utils.db_utils import hash_password
from fastapi.responses import JSONResponse
from typing import Any
from datetime import datetime, timezone


from schema.meter import AddMeterRequestBody, \
      UpdateMeterRequestBody, QueryReadingByTimeRangeBody, \
      QueryReadingLatestBody
from model.models import Meter, ReadingValue
from sqlalchemy.orm import Session
from sqlalchemy import func
import traceback

router = APIRouter()

import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = True

def _get_readingvalue_column_map() -> dict[str, Any]:
    """
    Column whitelist derived from the ORM model to prevent SQL injection
    via arbitrary column names.
    """
    # ReadingValue must be imported from your models module.
    return {c.name: c for c in ReadingValue.__table__.columns}


def _build_row(time_stamp: datetime, cols: list[str], row: Any) -> dict[str, Any]:
    # SQLAlchemy row from select() supports attribute access by label
    out: dict[str, Any] = {"time_stamp": time_stamp}
    for c in cols:
        out[c] = getattr(row, c)
    return out


def _format_time_stamp(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.replace(tzinfo=None)
        return value.isoformat()
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return value
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt.isoformat()
    return value

# @router.post("/query_data_by_time_range")
# def query_data_by_time_range(request: Request, body: QueryReadingByTimeRangeBody):
#     engine = request.app.state.engine
#     colmap: dict[str, Any] = _get_readingvalue_column_map()

#     invalid = [c for c in body.columns if c not in colmap]
#     if invalid:
#         raise HTTPException(
#             status_code=400,
#             detail={"error": "invalid_columns", "invalid": invalid},
#         )

#     # SQLAlchemy 1.x ORM Query API
#     # Always include timestamp
#     query_cols = [ReadingValue.time_stamp_utc.label("time_stamp")]
#     query_cols.extend(colmap[c].label(c) for c in body.columns)

#     try:
#         with Session(engine) as session:
#             q = (
#                 session.query(*query_cols)
#                 .filter(ReadingValue.meter_id == body.meter_id)
#                 .filter(ReadingValue.time_stamp_utc >= body.time_range.start_utc)
#                 .filter(ReadingValue.time_stamp_utc < body.time_range.end_utc)
#             )

#             if body.order == "asc":
#                 q = q.order_by(ReadingValue.time_stamp_utc.asc())
#             else:
#                 q = q.order_by(ReadingValue.time_stamp_utc.desc())

#             q = q.limit(body.limit)

#             rows = q.all()

#         # rows are row-like objects with attributes matching labels
#         data = [_build_row(getattr(r, "time_stamp"), body.columns, r) for r in rows]

#         return {
#             "meter_id": body.meter_id,
#             "columns": body.columns,
#             "time_range": {
#                 "start_utc": body.time_range.start_utc,
#                 "end_utc": body.time_range.end_utc,
#             },
#             "count": len(data),
#             "data": data,
#         }

#     except HTTPException:
#         raise
#     except Exception:
#         logger.error("Unhandled exception:\n%s", traceback.format_exc())
#         raise

@router.post("/query_data_by_time_range")
def query_data_by_time_range(request: Request, body: QueryReadingByTimeRangeBody):
    engine = request.app.state.engine
    colmap: dict[str, Any] = _get_readingvalue_column_map()

    invalid = [c for c in body.columns if c not in colmap]
    if invalid:
        raise HTTPException(status_code=400, detail={"error": "invalid_columns", "invalid": invalid})

    # if body.time_range.start_utc.tzinfo is None or body.time_range.end_utc.tzinfo is None:
    #     raise HTTPException(status_code=400, detail={"error": "datetime_not_timezone_aware"})

    start_utc = body.time_range.start_utc
    end_utc = body.time_range.end_utc

    try:
        with Session(engine) as session:
            if body.interval_seconds is None:
                # -------- raw rows --------
                query_cols = [ReadingValue.time_stamp_utc.label("time_stamp")]
                query_cols.extend(colmap[c].label(c) for c in body.columns)

                q = (
                    session.query(*query_cols)
                    .filter(ReadingValue.meter_id == body.meter_id)
                    .filter(ReadingValue.time_stamp_utc >= start_utc)
                    .filter(ReadingValue.time_stamp_utc < end_utc)
                )

                q = q.order_by(
                    ReadingValue.time_stamp_utc.asc()
                    if body.order == "asc"
                    else ReadingValue.time_stamp_utc.desc()
                ).limit(body.limit)

                rows = q.all()

                data = []
                for r in rows:
                    out = {"time_stamp": _format_time_stamp(getattr(r, "time_stamp"))}
                    for c in body.columns:
                        out[c] = getattr(r, c)
                    data.append(out)

            else:
                # -------- interval bucketed: FIRST row per bucket (for ALL columns) --------
                # Semantics: for each time bucket, pick the earliest row in that bucket and return its values.
                # Implementation: PostgreSQL DISTINCT ON(bucket_epoch) ORDER BY bucket_epoch, time_stamp_utc ASC
                interval = int(body.interval_seconds)
                if interval <= 0:
                    raise HTTPException(status_code=400, detail={"error": "interval_seconds_must_be_positive"})

                bucket_epoch = (
                    func.floor(func.extract("epoch", ReadingValue.time_stamp_utc) / interval) * interval
                ).label("bucket_epoch")

                # include bucket_epoch only to drive DISTINCT ON; we drop it from the final output
                base_cols = [bucket_epoch, ReadingValue.time_stamp_utc.label("time_stamp")]
                base_cols.extend(colmap[c].label(c) for c in body.columns)

                base_q = (
                    session.query(*base_cols)
                    .filter(ReadingValue.meter_id == body.meter_id)
                    .filter(ReadingValue.time_stamp_utc >= start_utc)
                    .filter(ReadingValue.time_stamp_utc < end_utc)
                    .order_by(bucket_epoch.asc(), ReadingValue.time_stamp_utc.asc())
                    .distinct(bucket_epoch)
                )

                base_sq = base_q.subquery("first_per_bucket")

                # project only what the API returns
                out_cols = [base_sq.c.time_stamp.label("time_stamp")]
                out_cols.extend(getattr(base_sq.c, c).label(c) for c in body.columns)

                q = session.query(*out_cols)

                q = q.order_by(
                    base_sq.c.time_stamp.asc() if body.order == "asc" else base_sq.c.time_stamp.desc()
                ).limit(body.limit)

                rows = q.all()

                data = []
                for r in rows:
                    out = {"time_stamp": _format_time_stamp(getattr(r, "time_stamp"))}
                    for c in body.columns:
                        out[c] = getattr(r, c)
                    data.append(out)

        return {
            "meter_id": body.meter_id,
            "columns": body.columns,
            "interval_seconds": body.interval_seconds,
            "time_range": {
                "start_utc": _format_time_stamp(start_utc),
                "end_utc": _format_time_stamp(end_utc),
            },
            "count": len(data),
            "data": data,
        }

    except HTTPException:
        raise
    except Exception:
        logger.error("Unhandled exception:\n%s", traceback.format_exc())
        raise


@router.post("/query_reading_latest")
def query_reading_latest(request: Request, body: QueryReadingLatestBody):
    engine = request.app.state.engine
    colmap: dict[str, Any] = _get_readingvalue_column_map()

    invalid = [c for c in body.columns if c not in colmap]
    if invalid:
        raise HTTPException(status_code=400, detail={"error": "invalid columns", "invalid": invalid})
    if body.count > 10000:
        raise HTTPException(status_code=400, detail={"error": "too many counts, maximum is 10000"})

    try:
        with Session(engine) as session:
            if body.interval_seconds is None:
                # -------- latest n raw rows --------
                query_cols = [ReadingValue.time_stamp_utc.label("time_stamp")]
                query_cols.extend(colmap[c].label(c) for c in body.columns)

                q = (
                    session.query(*query_cols)
                    .filter(ReadingValue.meter_id == body.meter_id)
                    .order_by(ReadingValue.time_stamp_utc.desc())
                    .limit(body.count)
                )

                rows = q.all()

                if body.order == "asc":
                    rows = list(reversed(rows))

                data: list[dict[str, Any]] = []
                for r in rows:
                    out: dict[str, Any] = {"time_stamp": _format_time_stamp(getattr(r, "time_stamp"))}
                    for c in body.columns:
                        out[c] = getattr(r, c)
                    data.append(out)

                return {
                        "meter_id": body.meter_id,
                        "columns": body.columns,
                        "count": len(data),
                        "order": body.order,
                        "interval_seconds": body.interval_seconds,
                        "data": data,
                    }
                

            # -------- latest n buckets, first row per bucket --------
            interval = int(body.interval_seconds)
            if interval <= 0:
                raise HTTPException(status_code=400, detail={"error": "interval_seconds_must_be_positive"})

            bucket_epoch = (
                func.floor(func.extract("epoch", ReadingValue.time_stamp_utc) / interval) * interval
            ).label("bucket_epoch")

            base_cols = [bucket_epoch, ReadingValue.time_stamp_utc.label("time_stamp")]
            base_cols.extend(colmap[c].label(c) for c in body.columns)

            # Pick FIRST row in each bucket by ordering time ascending inside bucket.
            # Then take the latest buckets by ordering buckets descending and limiting.
            first_per_bucket_q = (
                session.query(*base_cols)
                .filter(ReadingValue.meter_id == body.meter_id)
                .order_by(bucket_epoch.desc(), ReadingValue.time_stamp_utc.asc())
                .distinct(bucket_epoch)
                .limit(body.count)
            )

            sq = first_per_bucket_q.subquery("first_per_bucket")

            out_cols = [sq.c.time_stamp.label("time_stamp")]
            out_cols.extend(getattr(sq.c, c).label(c) for c in body.columns)

            q2 = session.query(*out_cols).order_by(
                sq.c.time_stamp.asc() if body.order == "asc" else sq.c.time_stamp.desc()
            )

            rows2 = q2.all()

            data2: list[dict[str, Any]] = []
            for r in rows2:
                out: dict[str, Any] = {"time_stamp": _format_time_stamp(getattr(r, "time_stamp"))}
                for c in body.columns:
                    out[c] = getattr(r, c)
                data2.append(out)

            return {
                    "meter_id": body.meter_id,
                    "columns": body.columns,
                    "count": len(data2),
                    "order": body.order,
                    "interval_seconds": body.interval_seconds,
                    "data": data2,
                }

    except HTTPException:
        raise
    except Exception:
        logger.error("Unhandled exception:\n%s", traceback.format_exc())
        raise


