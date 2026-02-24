from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, List, Literal
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StrictStr, constr, field_validator

from driver.edmi_enums import EDMI_ERROR_CODE, serialize_error
from driver.meters_config import PASWORD, SERIAL_NUMBER, USERNAME

router = APIRouter()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = True

class ReadMetersBody(BaseModel):
    meters_id_list: List[int]

class ReadProfileBody(BaseModel):
    meter_id: int
    serial_number: int | None = None
    username: str | None = None
    password: str | None = None
    survey: str
    from_datetime: date
    to_datetime: date
    max_records: int | None = None

class ReadProfileLoopBody(BaseModel):
    meters_id_list: list[int]
    survey: str = "LS02"

class AddMeterRequestBody(BaseModel):
    serial_number: int = Field(..., description="Meter serial number")
    username: str = Field(..., description="Meter username")
    password: str = Field(..., description="Meter password")
    owner_id: int = Field(..., description="Owner ID")
    meter_name: Optional[str] = Field(None, description="Meter name", max_length=100)
    outstation: Optional[int] = Field(None, description="Outstation number")
    type: str = Field(..., description="Meter type", max_length=20)
    model: str = Field(..., description="Meter model", max_length=20)
    survey_type: Optional[List[str]] = Field(
        None,
        description="Survey types for this meter",
    )


class UpdateMeterRequestBody(BaseModel):
    serial_number: int = Field(..., description="Meter serial number")
    username: str = Field(..., description="Meter username")
    password: str = Field(..., description="Meter password")
    owner_id: int = Field(..., description="Owner ID")
    meter_name: Optional[str] = Field(None, description="Meter name", max_length=100)
    outstation: Optional[int] = Field(None, description="Outstation number")
    type: str = Field(..., description="Meter type", max_length=20)
    model: str = Field(..., description="Meter model", max_length=20)
    survey_type: Optional[List[str]] = Field(
        None,
        description="Survey types for this meter",
    )

class TimeRange(BaseModel):
    start_utc: datetime = Field(..., description="Inclusive start (UTC). ISO8601.")
    end_utc: datetime = Field(..., description="Exclusive end (UTC). ISO8601.")

    @field_validator("end_utc")
    @classmethod
    def _end_after_start(cls, end_utc: datetime, info):
        start_utc = info.data.get("start_utc")
        if start_utc is not None and end_utc <= start_utc:
            raise ValueError("end_utc must be greater than start_utc")
        return end_utc


class QueryReadingByTimeRangeBody(BaseModel):
    meter_id: int = Field(..., ge=1)
    columns: list[str] = Field(..., min_length=1, description="ReadingValue column names")
    time_range: TimeRange
    limit: int = Field(5000, ge=1, le=200_000)
    order: Literal["asc", "desc"] = "asc"

    interval_seconds: int | None = Field(
        default=None,
        ge=1,
        le=86_400,
        description="Downsample interval in seconds. None returns all rows.",
        )

    @field_validator("columns")
    @classmethod
    def _nonempty_unique(cls, cols: list[str]) -> list[str]:
        cols = [c.strip() for c in cols if c and c.strip()]
        if not cols:
            raise ValueError("columns must not be empty")
        # preserve order, unique
        seen: set[str] = set()
        out: list[str] = []
        for c in cols:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out


class QueryReadingLatestBody(BaseModel):
    meter_id: int = Field(..., ge=1, description="Meter ID to query")
    columns: list[str] = Field(..., min_length=1, description="ReadingValue column names to return")
    count: int = Field(10, ge=1, le=50_000, description="Number of rows to return after interval sampling")
    order: Literal["asc", "desc"] = Field(
        default="desc",
        description="Sort order by time_stamp_utc. desc returns newest-first; asc returns oldest-first among the selected n.",
    )

    # NEW: interval in seconds (None => raw latest n rows)
    interval_seconds: int | None = Field(
        default=None,
        ge=1,
        le=86_400,
        description="Downsample interval in seconds. None returns latest raw rows.",
    )

    @field_validator("columns")
    @classmethod
    def _nonempty_unique(cls, cols: list[str]) -> list[str]:
        cols = [c.strip() for c in cols if c and c.strip()]
        if not cols:
            raise ValueError("columns must not be empty")
        seen: set[str] = set()
        out: list[str] = []
        for c in cols:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out
