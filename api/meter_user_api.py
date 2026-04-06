import asyncio
import json
import time
from fastapi import APIRouter, Request, HTTPException
from driver.meters_config import USERNAME, PASWORD, SERIAL_NUMBER
from driver.edmi_enums import serialize_error, EDMI_ERROR_CODE
from utils.utils import format_list_registers
from db_utils.db_utils import hash_password
from fastapi.responses import JSONResponse

from schema.meter import AddMeterRequestBody, UpdateMeterRequestBody
from model.models import Meter
from sqlalchemy.orm import Session
import traceback

router = APIRouter()

import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = True

@router.post("/add_meter")
def add_meter(request: Request, body: AddMeterRequestBody):
    engine = request.app.state.engine

    meter = Meter(
        serial_number=body.serial_number,
        username=body.username,
        password=body.password,
        owner_id=body.owner_id,
        # optional
        meter_name=getattr(body, "meter_name", None),
        outstation=getattr(body, "outstation", None),
        type=body.type,
        model=body.model,
        role_id=getattr(body, "role", None),
        source_id=getattr(body, "source_id", None),
        survey_type=getattr(body, "survey_type", None),
    )

    try:
        with Session(engine) as session:
            exist: Meter | None = (
                session.query(Meter)
                .filter(Meter.serial_number == str(body.serial_number))
                .first()
            )

            if exist:
                return {
                    "serial_number": body.serial_number,
                    "status": "meter with the same serial number already exists",
                }

            session.add(meter)
            session.commit()

        return {
            "serial_number": body.serial_number,
            "status": "create meter successfully",
        }

    except Exception:
        logger.error("Unhandled exception:\n%s", traceback.format_exc())
        raise


@router.get("/get_all_meters_info")
def get_all_meters_info(request: Request):
    engine = request.app.state.engine
    try:
        with Session(engine) as session:
            meter_obj_all = session.query(Meter).all()

        return [
            {
                "meter_id": m.id,
                "serial_number": m.serial_number,
                "password": m.password,
                "username": m.username,
                "owner_id": m.owner_id,         
                # new fields
                "meter_name": m.meter_name,
                "outstation": m.outstation,
                "type": m.type,
                "model": m.model,
                "survey_type": m.survey_type or [],
                "role": m.role_id,
                "source_id": m.source_id,

            }
            for m in meter_obj_all
        ]

    except HTTPException:
        raise
    except Exception:
        logger.error("Unhandled exception:\n%s", traceback.format_exc())
        raise


@router.put("/update_meter")
def update_meter(
    request: Request,
    body: UpdateMeterRequestBody,
):
    engine = request.app.state.engine
    try:
        with Session(engine) as session:
            meter: Meter | None = (
                session.query(Meter)
                .filter(Meter.serial_number == str(body.serial_number))
                .first()
            )

            if not meter:
                return JSONResponse(
                    {
                        "status": "meter not found. Do you want to add it first?",
                        "serial_number": None,
                    }
                )

            meter.username = body.username
            meter.password = body.password
            meter.owner_id = body.owner_id

            # new fields (only update if present on the request body)
            if hasattr(body, "meter_name"):
                meter.meter_name = body.meter_name
            if hasattr(body, "outstation"):
                meter.outstation = body.outstation
            meter.type = body.type
            meter.model = body.model
            if hasattr(body, "survey_type") and body.survey_type is not None:
                meter.survey_type = body.survey_type
            if hasattr(body, "role") and body.role is not None:
                meter.role_id = body.role
            if hasattr(body, "source_id"):
                meter.source_id = body.source_id    
            session.commit()

        return {
            "status": "meter updated successfully",
            "serial_number": body.serial_number,
        }

    except HTTPException:
        raise
    except Exception:
        logger.error("Unhandled exception:\n%s", traceback.format_exc())
        raise


@router.delete("/delete_meter/{meter_id}")
def delete_meter(request: Request, meter_id: int):
    engine = request.app.state.engine

    try:
        with Session(engine) as session:
            meter: Meter | None = (
                session.query(Meter)
                .filter(Meter.id == meter_id)
                .first()
            )

            if not meter:
                raise HTTPException(status_code=404, detail="Meter not found")

            session.delete(meter)
            session.commit()

        return {
            "status": "Meter deleted successfully",
            "meter_id": meter_id,
        }

    except HTTPException:
        raise
    except Exception:
        logger.error("Unhandled exception:\n%s", traceback.format_exc())
        raise
