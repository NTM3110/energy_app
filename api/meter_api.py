# api/one_time_call.py (your endpoint file where read_and_save_meters_loop endpoint lives)
import asyncio
import json
import time
import uuid
from datetime import datetime, time as dt_time, timedelta
import redis
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from background_service.celery_app import celery_app
from background_service.state import Keys
from background_service.scheduler import TaskScheduler
from schema.meter import ReadMetersBody, ReadProfileBody, ReadProfileLoopBody
from driver.interface.edmi_structs import EDMISurvey
from model.models import Meter
from runtime_settings import REDIS_URL
from celery.exceptions import TimeoutError as CeleryTimeoutError

router = APIRouter(tags=["one-time-call"])


def _redis() -> redis.Redis:
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)

def _meter_status_channel_key(keys: Keys, task_id: str) -> str:
    return f"{keys.meter_status_channel_prefix}:{task_id}"


def _meter_status_list_key(keys: Keys, task_id: str) -> str:
    return f"{keys.meter_status_list_prefix}:{task_id}"


def _parse_last_event_id(request: Request) -> int:
    raw = request.headers.get("last-event-id")
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def _load_event(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _format_sse(event_id: int | None, event_type: str | None, data: dict) -> str:
    payload = json.dumps(data, separators=(",", ":"))
    parts: list[str] = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    if event_type:
        parts.append(f"event: {event_type}")
    parts.append(f"data: {payload}")
    return "\n".join(parts) + "\n\n"


@router.post("/read_and_save_meters_loop")
async def read_and_save_meters_loop(request: Request, body: ReadMetersBody):
    r = _redis()
    keys = Keys()
    scheduler = TaskScheduler(r, keys)
    engine = request.app.state.engine

    with Session(engine) as session:
        meters = (
            session.query(Meter)
            .filter(Meter.id.in_(body.meters_id_list))
            .all()
        )

    existing_ids = {m.id for m in meters}
    if not existing_ids:
        scheduler.stop_loop()
        return JSONResponse(
            {
                "status": "No ID available",
                "task_id": None,
                "available_ids": None,
                "functional_ids": [],
            }
        )

    existing_task_id = scheduler.get_loop_task_id()
    if existing_task_id:
        functional_ids = scheduler.get_prelogin_result(existing_task_id) or []
        return JSONResponse(
            {
                "status": "Already running",
                "task_id": existing_task_id,
                "available_ids": list(existing_ids),
                "functional_ids": functional_ids if isinstance(functional_ids, list) else [],
            }
        )

    task_id = uuid.uuid4().hex
    if not scheduler.register_loop_task(task_id, priority=0):
        existing_task_id = scheduler.get_loop_task_id()
        functional_ids = scheduler.get_prelogin_result(existing_task_id) if existing_task_id else []
        return JSONResponse(
            {
                "status": "Already running",
                "task_id": existing_task_id,
                "available_ids": list(existing_ids),
                "functional_ids": functional_ids if isinstance(functional_ids, list) else [],
            }
        )

    async_result = celery_app.send_task(
        "read_and_save_meters_loop",
        kwargs={"meter_ids": list(existing_ids)},
        task_id=task_id,
    )

    functional_ids = await scheduler.wait_prelogin_result(
        async_result.id,
        timeout_s=20.0,
    )

    if functional_ids is None:
        return JSONResponse(
            {
                "status": "started_but_prelogin_timeout",
                "task_id": async_result.id,
                "available_ids": list(existing_ids),
                "functional_ids": None,
            }
        )

    return JSONResponse(
        {
            "status": "started",
            "task_id": async_result.id,
            "available_ids": list(existing_ids),
            "functional_ids": functional_ids,
        }
    )


@router.post("/read_and_save_meters_loop_streaming_status")
async def read_and_save_meters_loop_streaming_status(request: Request, body: ReadMetersBody):
    r = _redis()
    keys = Keys()
    scheduler = TaskScheduler(r, keys)
    engine = request.app.state.engine

    with Session(engine) as session:
        meters = (
            session.query(Meter)
            .filter(Meter.id.in_(body.meters_id_list))
            .all()
        )

    existing_ids = {m.id for m in meters}
    if not existing_ids:
        async def _empty_stream():
            payload = {
                "status": "No ID available",
                "task_id": None,
                "available_ids": None,
                "functional_ids": [],
                "meter_status": [],
            }
            yield _format_sse(None, "status", payload)

        return StreamingResponse(
            _empty_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    existing_task_id = scheduler.get_loop_task_id()
    if existing_task_id:
        functional_ids = scheduler.get_prelogin_result(existing_task_id) or []
        task_id = existing_task_id
        start_payload = {
            "status": "Already running",
            "task_id": task_id,
            "available_ids": list(existing_ids),
            "functional_ids": functional_ids if isinstance(functional_ids, list) else [],
            "meter_status": [],
        }
    else:
        task_id = uuid.uuid4().hex
        if not scheduler.register_loop_task(task_id, priority=0):
            existing_task_id = scheduler.get_loop_task_id()
            functional_ids = scheduler.get_prelogin_result(existing_task_id) if existing_task_id else []
            start_payload = {
                "status": "Already running",
                "task_id": existing_task_id,
                "available_ids": list(existing_ids),
                "functional_ids": functional_ids if isinstance(functional_ids, list) else [],
                "meter_status": [],
            }
        else:
            async_result = celery_app.send_task(
                "read_and_save_meters_loop_sreaming_status",
                kwargs={"meter_ids": list(existing_ids)},
                task_id=task_id,
            )
            task_id = async_result.id

            functional_ids = await scheduler.wait_prelogin_result(
                task_id,
                timeout_s=20.0,
            )

            if functional_ids is None:
                start_payload = {
                    "status": "started_but_prelogin_timeout",
                    "task_id": task_id,
                    "available_ids": list(existing_ids),
                    "functional_ids": None,
                    "meter_status": [],
                }
            else:
                start_payload = {
                    "status": "started",
                    "task_id": task_id,
                    "available_ids": list(existing_ids),
                    "functional_ids": functional_ids,
                    "meter_status": [],
                }

    last_event_id = _parse_last_event_id(request)
    channel = _meter_status_channel_key(keys, task_id)
    list_key = _meter_status_list_key(keys, task_id)
    latest = _load_event(r.lindex(list_key, -1))
    if latest:
        data = latest.get("data", {})
        if isinstance(data, dict) and "meter_status" in data:
            start_payload["meter_status"] = data.get("meter_status") or []

    async def _stream():
        yield _format_sse(None, "status", start_payload)

        backlog = r.lrange(list_key, 0, -1)
        current_last_id = last_event_id
        for raw in backlog:
            event = _load_event(raw)
            if not event:
                continue
            event_id = event.get("id", 0)
            if event_id <= current_last_id:
                continue
            yield _format_sse(event_id, event.get("event"), event.get("data", {}))
            current_last_id = event_id

        pubsub = r.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(channel)
        last_ping = time.time()
        try:
            while True:
                msg = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
                if msg:
                    event = _load_event(msg.get("data"))
                    if not event:
                        continue
                    event_id = event.get("id", 0)
                    if event_id <= current_last_id:
                        continue
                    yield _format_sse(event_id, event.get("event"), event.get("data", {}))
                    current_last_id = event_id
                    last_ping = time.time()
                else:
                    if time.time() - last_ping > 30:
                        yield ": keep-alive\n\n"
                        last_ping = time.time()
        except asyncio.CancelledError:
            pass
        finally:
            try:
                pubsub.unsubscribe(channel)
            except Exception:
                pass
            try:
                pubsub.close()
            except Exception:
                pass

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/test_login_meters")
async def test_login_meters(request: Request, body: ReadMetersBody):
    r = _redis()
    keys = Keys()
    scheduler = TaskScheduler(r, keys)
    engine = request.app.state.engine

    with Session(engine) as session:
        meters = (
            session.query(Meter)
            .filter(Meter.id.in_(body.meters_id_list))
            .all()
        )

    existing_ids = {m.id for m in meters}
    if not existing_ids:
        return JSONResponse(
            {
                "status": "No ID available",
                "task_id": None,
                "available_ids": None,
                "login_ids": [],
            }
        )

    async_result = celery_app.send_task(
        "test_login_meters",
        kwargs={"meter_ids": list(existing_ids)},
    )

    login_ids = await scheduler.wait_prelogin_result(
        async_result.id,
        timeout_s=20.0,
    )

    if login_ids is None:
        return JSONResponse(
            {
                "status": "started_but_login_timeout",
                "task_id": async_result.id,
                "available_ids": list(existing_ids),
                "login_ids": None,
            }
        )

    return JSONResponse(
        {
            "status": "completed",
            "task_id": async_result.id,
            "available_ids": list(existing_ids),
            "login_ids": login_ids,
        }
    )



@router.post("/read_and_save_profile_loop_streaming_status")
async def read_and_save_profile_loop_streaming_status(request: Request, body: ReadProfileLoopBody):
    r = _redis()
    keys = Keys()
    # Unique loop_name so it doesn't conflict with main reading loop
    scheduler = TaskScheduler(r, keys, loop_name="profile")
    engine = request.app.state.engine

    with Session(engine) as session:
        meters = (
            session.query(Meter)
            .filter(Meter.id.in_(body.meters_id_list))
            .all()
        )

    existing_ids = {m.id for m in meters}
    if not existing_ids:
        async def _empty_stream():
            payload = {
                "status": "No ID available",
                "task_id": None,
                "available_ids": None,
                "functional_ids": [],
                "meter_status": [],
            }
            yield _format_sse(None, "status", payload)

        return StreamingResponse(
            _empty_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    existing_task_id = scheduler.get_loop_task_id()
    if existing_task_id:
        functional_ids = scheduler.get_prelogin_result(existing_task_id) or []
        task_id = existing_task_id
        start_payload = {
            "status": "Already running",
            "task_id": task_id,
            "available_ids": list(existing_ids),
            "functional_ids": functional_ids if isinstance(functional_ids, list) else [],
            "meter_status": [],
        }
    else:
        task_id = uuid.uuid4().hex
        if not scheduler.register_loop_task(task_id, priority=0):
            existing_task_id = scheduler.get_loop_task_id()
            functional_ids = scheduler.get_prelogin_result(existing_task_id) if existing_task_id else []
            start_payload = {
                "status": "Already running",
                "task_id": existing_task_id,
                "available_ids": list(existing_ids),
                "functional_ids": functional_ids if isinstance(functional_ids, list) else [],
                "meter_status": [],
            }
        else:
            async_result = celery_app.send_task(
                "read_and_save_profile_loop_streaming_status",
                kwargs={"meter_ids": list(existing_ids), "survey": body.survey},
                task_id=task_id,
            )
            task_id = async_result.id

            functional_ids = await scheduler.wait_prelogin_result(
                task_id,
                timeout_s=20.0,
            )

            if functional_ids is None:
                start_payload = {
                    "status": "started_but_prelogin_timeout",
                    "task_id": task_id,
                    "available_ids": list(existing_ids),
                    "functional_ids": None,
                    "meter_status": [],
                }
            else:
                start_payload = {
                    "status": "started",
                    "task_id": task_id,
                    "available_ids": list(existing_ids),
                    "functional_ids": functional_ids,
                    "meter_status": [],
                }

    last_event_id = _parse_last_event_id(request)
    channel = _meter_status_channel_key(keys, task_id)
    list_key = _meter_status_list_key(keys, task_id)
    latest = _load_event(r.lindex(list_key, -1))
    if latest:
        data = latest.get("data", {})
        if isinstance(data, dict) and "meter_status" in data:
            start_payload["meter_status"] = data.get("meter_status") or []

    async def _stream():
        yield _format_sse(None, "status", start_payload)

        backlog = r.lrange(list_key, 0, -1)
        current_last_id = last_event_id
        for raw in backlog:
            event = _load_event(raw)
            if not event:
                continue
            event_id = event.get("id", 0)
            if event_id <= current_last_id:
                continue
            yield _format_sse(event_id, event.get("event"), event.get("data", {}))
            current_last_id = event_id

        pubsub = r.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(channel)
        last_ping = time.time()
        try:
            while True:
                msg = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
                if msg:
                    event = _load_event(msg.get("data"))
                    if not event:
                        continue
                    event_id = event.get("id", 0)
                    if event_id <= current_last_id:
                        continue
                    yield _format_sse(event_id, event.get("event"), event.get("data", {}))
                    current_last_id = event_id
                    last_ping = time.time()
                else:
                    if time.time() - last_ping > 30:
                        yield ": keep-alive\n\n"
                        last_ping = time.time()
        except asyncio.CancelledError:
            pass
        finally:
            try:
                pubsub.unsubscribe(channel)
            except Exception:
                pass
            try:
                pubsub.close()
            except Exception:
                pass

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )

@router.get("/read_and_save_profile_loop_stop")
async def read_and_save_profile_loop_stop(request: Request):
    r = _redis()
    keys = Keys()
    scheduler = TaskScheduler(r, keys, loop_name="profile")

    task_id = scheduler.stop_loop()
    if not task_id:
        return JSONResponse({"status": "not_running", "task_id": None})

    return JSONResponse({"status": "stopping", "task_id": task_id})


@router.get("/meter_loop_status")
async def meter_loop_status(request: Request):
    """
    Lightweight polling endpoint.
    Returns the current loop state and latest meter statuses from Redis.
    No body required — safe to call from the UI on an interval.
    """
    r = _redis()
    keys = Keys()
    scheduler = TaskScheduler(r, keys)

    task_id = scheduler.get_loop_task_id()
    loop_state = scheduler.get_loop_state() if task_id else "stopped"
    is_running = loop_state in ("running", "starting", "paused") if task_id else False

    functional_ids: list = []
    meter_status: list = []
    slot_ts: str | None = None

    if task_id:
        functional_ids = scheduler.get_prelogin_result(task_id) or []

        list_key = _meter_status_list_key(keys, task_id)
        raw = r.lindex(list_key, -1)
        if raw:
            try:
                event = json.loads(raw)
                data = event.get("data", {})
                meter_status = data.get("meter_status", [])
                slot_ts = data.get("slot_ts")
            except Exception:
                pass

    return JSONResponse({
        "task_id": task_id,
        "loop_state": loop_state,
        "is_running": is_running,
        "functional_ids": functional_ids if isinstance(functional_ids, list) else [],
        "meter_status": meter_status,
        "slot_ts": slot_ts,
    })


@router.get("/read_and_save_meters_loop_stop")
async def read_and_save_meters_loop_stop(request: Request):
    """
    Safe stop:
    - Idempotent: calling multiple times is fine.
    - Cooperative stop: scheduler loop control is set to stop.
    - Clears the loop task id so new runs can start immediately.
    - Best-effort completes prelogin waiters by writing prelogin state in Redis.
    """

    r = _redis()
    keys = Keys()
    scheduler = TaskScheduler(r, keys)

    task_id = scheduler.stop_loop()
    if not task_id:
        return JSONResponse({"status": "not_running", "task_id": None})

    return JSONResponse({"status": "stopping", "task_id": task_id})


@router.post("/read_profile")
async def read_profile(request: Request, body: ReadProfileBody):
    r = _redis()
    keys = Keys()
    scheduler = TaskScheduler(r, keys)
    engine = request.app.state.engine

    try:
        survey_enum = EDMISurvey[body.survey]
    except KeyError:
        return JSONResponse(
            {
                "status": "invalid_survey",
                "survey": body.survey,
            },
            status_code=400,
        )

    def _fetch_meter(meter_id: int) -> Meter | None:
        with Session(engine) as session:
            return (
                session.query(Meter)
                .filter(Meter.id == meter_id)
                .one_or_none()
            )

    meter = await asyncio.to_thread(_fetch_meter, body.meter_id)
    if meter is None:
        return JSONResponse(
            {"status": "meter_not_found", "meter_id": body.meter_id},
            status_code=404,
        )

    survey_interval_seconds = {
        EDMISurvey.LS01: 1800,
        EDMISurvey.LS03: 300,
    }.get(survey_enum, 0)
    from_dt = datetime.combine(body.from_datetime, dt_time(0, 0, 0)) + timedelta(seconds=survey_interval_seconds)
    to_dt = datetime.combine(body.to_datetime, dt_time(0, 0, 0)) + timedelta(days=1)
    print("From_dt: ", from_dt.isoformat())
    print("To_dt: ", to_dt.isoformat())
    print("Survey: ", survey_enum)
    print("Meter ID: ", body.meter_id)
    print("Serial Number: ", meter.serial_number)
    print("Username: ", meter.username)
    print("Password: ", meter.password)
    existing_task_id = scheduler.get_loop_task_id()
    if not existing_task_id:
        async_result = celery_app.send_task(
            "read_profile_once",
            kwargs={
                "meter_id": body.meter_id,
                "serial_number": meter.serial_number,
                "username": meter.username,
                "password": meter.password,
                "survey": int(survey_enum),
                "from_datetime": from_dt.isoformat(),
                "to_datetime": to_dt.isoformat(),
            },
        )

        try:
            result = await asyncio.to_thread(async_result.get, timeout=120.0)
        except CeleryTimeoutError:
            return JSONResponse(
                {
                    "status": "timeout",
                    "meter_id": body.meter_id,
                    "survey": body.survey,
                    "field": [],
                    "interval_seconds": None,
                    "count": 0,
                    "data": [],
                }
            )

        return JSONResponse(result)

    if scheduler.has_pending_task("read_profile"):
        return JSONResponse(
            {"status": "profile_busy", "meter_id": body.meter_id},
            status_code=409,
        )

    payload = {
        "meter_id": body.meter_id,
        "serial_number": meter.serial_number,
        "username": meter.username,
        "password": meter.password,
        "survey": int(survey_enum),
        "from_datetime": from_dt.isoformat(),
        "to_datetime": to_dt.isoformat(),
    }
    task_id = scheduler.enqueue_once(
        name="read_profile",
        payload=payload,
        priority=-1,
        singleflight=True,
    )
    if not task_id:
        return JSONResponse(
            {"status": "profile_busy", "meter_id": body.meter_id},
            status_code=409,
        )

    timeout_s = 120.0
    result = await scheduler.wait_task_result(task_id, timeout_s=timeout_s)
    if result is not None:
        return JSONResponse(result)
    return JSONResponse(
        {
            "status": "timeout",
            "meter_id": body.meter_id,
            "survey": body.survey,
            "field": [],
            "interval_seconds": None,
            "count": 0,
            "data": [],
        }
    )
