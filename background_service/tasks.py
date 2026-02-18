# background_service/tasks.py
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

import redis
from celery import Task
from sqlalchemy.orm import Session

from .celery_app import celery_app
from .state import Keys
from .providers import get_meter_service, get_bus_sem, get_engine
from .scheduler import TaskScheduler, LoopControl, LoopState
from utils.utils import serialize_error, format_parsed_profile_data
from driver.edmi_enums import EDMI_ERROR_CODE
from driver.interface.edmi_structs import EDMISurvey
from model.models import Meter, ReadingValue
from db_utils.db_utils import map_registers_to_reading_columns
from runtime_settings import REDIS_URL

import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = True


def _redis() -> redis.Redis:
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


class BaseTask(Task):
    autoretry_for: tuple[type[Exception], ...] = ()
    retry_backoff: bool = False


def _survey_name(value: int) -> str:
    try:
        return EDMISurvey(value).name
    except Exception:
        return str(value)




def _meter_status_channel_key(keys: Keys, task_id: str) -> str:
    return f"{keys.meter_status_channel_prefix}:{task_id}"


def _meter_status_list_key(keys: Keys, task_id: str) -> str:
    return f"{keys.meter_status_list_prefix}:{task_id}"


def _meter_status_seq_key(keys: Keys, task_id: str) -> str:
    return f"{keys.meter_status_seq_prefix}:{task_id}"


def _publish_meter_status(
    r: redis.Redis,
    keys: Keys,
    *,
    task_id: str,
    meter_status: list[dict[str, Any]],
    slot_ts: datetime | None = None,
    event_type: str = "meter_status",
) -> None:
    payload: dict[str, Any] = {
        "task_id": task_id,
        "meter_status": meter_status,
    }
    if slot_ts is not None:
        payload["slot_ts"] = slot_ts.isoformat()

    seq = r.incr(_meter_status_seq_key(keys, task_id))
    event = {
        "id": int(seq),
        "event": event_type,
        "data": payload,
    }
    encoded = json.dumps(event, separators=(",", ":"))

    pipe = r.pipeline(transaction=False)
    list_key = _meter_status_list_key(keys, task_id)
    pipe.rpush(list_key, encoded)
    pipe.ltrim(list_key, -1000, -1)
    pipe.expire(list_key, 3600)
    pipe.expire(_meter_status_seq_key(keys, task_id), 3600)
    pipe.execute()

    r.publish(_meter_status_channel_key(keys, task_id), encoded)


def _run_profile_read(
    *,
    service: Any,
    sem: Any,
    meter_id: int,
    serial_number: int,
    username: str,
    password: str,
    survey: int,
    from_datetime: str,
    to_datetime: str,
    max_records: int | None,
) -> dict[str, Any]:
    try:
        from_dt = datetime.fromisoformat(from_datetime)
        to_dt = datetime.fromisoformat(to_datetime)
    except ValueError:
        logger.error("read_profile_once: invalid datetime format")
        return {
            "status": "invalid_datetime",
            "meter_id": meter_id,
            "survey": _survey_name(survey),
            "field": [],
            "interval_seconds": None,
            "count": 0,
            "data": [],
        }

    sem.acquire()
    try:
        profile_spec, fields, err_code = service.media.edmi_read_profile(
            username=username,
            password=password,
            serial_number=serial_number,
            survey=survey,
            from_datetime=from_dt,
            to_datetime=to_dt,
            max_records=max_records,
            keep_open=False,
            do_login=True,
        )
    finally:
        sem.release()

    if err_code != EDMI_ERROR_CODE.NONE:
        logger.warning(
            "read_profile_once failed: serial=%s err=%s",
            serial_number,
            serialize_error(err_code),
        )
        return {
            "status": "error",
            "meter_id": meter_id,
            "survey": _survey_name(survey),
            "field": [],
            "interval_seconds": None,
            "count": 0,
            "data": [],
        }

    records = format_parsed_profile_data(profile_spec, fields, time_key="time_stamp")
    field_names = [ch.Name for ch in profile_spec.ChannelsInfo[: profile_spec.ChannelsCount]]
    sample = records[0] if records else None
    logger.info(
        "read_profile_once ok: serial=%s count=%s sample=%s",
        serial_number,
        len(records),
        sample,
    )
    return {
        "status": "ok",
        "meter_id": meter_id,
        "survey": _survey_name(survey),
        "field": field_names,
        "interval_seconds": profile_spec.Interval,
        "count": len(records),
        "data": records,
    }


@celery_app.task(bind=True, base=BaseTask, name="read_and_save_meters_loop")
def read_and_save_meters_loop(self, meter_ids) -> str:
    r = _redis()
    keys = Keys()
    task_id: str = self.request.id
    scheduler = TaskScheduler(r, keys)

    # ---- per-task prelogin state reset ----
    scheduler.clear_prelogin(task_id)
    if scheduler.get_loop_control() == LoopControl.STOP:
        scheduler.set_prelogin_result(task_id, [])
        scheduler.set_loop_state(LoopState.STOPPED)
        scheduler.clear_loop_task()
        return "stopped"
    scheduler.force_register_loop_task(task_id, priority=0)

    service = get_meter_service()
    sem = get_bus_sem()
    engine = get_engine()

    def _should_stop() -> bool:
        return scheduler.get_loop_control() == LoopControl.STOP

    def _should_pause() -> bool:
        return scheduler.get_loop_control() == LoopControl.PAUSE

    def _run_once_task_if_ready() -> bool:
        ran_any = False
        loop_priority = scheduler.get_loop_priority()
        while True:
            task = scheduler.claim_next_task(max_priority=loop_priority)
            if not task:
                break
            ran_any = True
            scheduler.set_loop_state(LoopState.PAUSED)
            try:
                if task.get("name") == "read_profile":
                    payload = task.get("payload") or {}
                    result = _run_profile_read(
                        service=service,
                        sem=sem,
                        meter_id=payload.get("meter_id"),
                        serial_number=payload.get("serial_number"),
                        username=payload.get("username"),
                        password=payload.get("password"),
                        survey=payload.get("survey"),
                        from_datetime=payload.get("from_datetime"),
                        to_datetime=payload.get("to_datetime"),
                        max_records=payload.get("max_records"),
                    )
                    scheduler.complete_task(task["task_id"], result)
                else:
                    scheduler.fail_task(task["task_id"], "unknown_task")
            except Exception:
                logger.exception("scheduled task failed")
                scheduler.fail_task(task["task_id"], "exception")
            finally:
                if not _should_stop():
                    scheduler.set_loop_state(LoopState.RUNNING)
        return ran_any

    def _wait_if_paused() -> bool:
        if not _should_pause():
            return True
        scheduler.set_loop_state(LoopState.PAUSED)
        try:
            while _should_pause():
                if _should_stop():
                    return False
                _run_once_task_if_ready()
                time.sleep(0.2)
        finally:
            if not _should_stop():
                scheduler.set_loop_state(LoopState.RUNNING)
        return True

    def _floor_to_30s_slot(ts: datetime) -> datetime:
        # Normalize to exactly ..:..:00 or ..:..:30 (UTC)
        slot_second = 0 if ts.second < 30 else 30
        return ts.replace(second=slot_second, microsecond=0)

    def _next_30s_boundary(now: datetime) -> datetime:
        # If already exactly on a boundary, return it; otherwise return the next boundary.
        floored = _floor_to_30s_slot(now)
        if now == floored:
            return floored
        return floored + timedelta(seconds=30)

    def _sleep_until(target: datetime, max_chunk_seconds: float = 0.2) -> bool:
        # Returns False if stopped while waiting, True otherwise.
        while True:
            if _should_stop():
                return False
            if _should_pause():
                if not _wait_if_paused():
                    return False
            if scheduler.has_runnable_task(max_priority=scheduler.get_loop_priority()):
                _run_once_task_if_ready()
            now = datetime.now(timezone.utc)
            remaining = (target - now).total_seconds()
            if remaining <= 0:
                return True
            time.sleep(min(remaining, max_chunk_seconds))

    @dataclass(frozen=True)
    class MeterCtx:
        meter_id: int
        serial_number: int
        username: str
        password: str
        driver_meter: Any

    with Session(engine) as session:
        db_meters: list[Meter] = (
            session.query(Meter)
            .filter(Meter.id.in_(meter_ids))
            .all()
        )

    if not db_meters:
        raise ValueError("No meters registered")

    ctxs: list[MeterCtx] = []
    for m in db_meters:
        drv = service.get_meter(
            serial=int(m.serial_number) if str(m.serial_number).isdigit() else 0,
            username=m.username,
            password=m.password,
        )
        drv.init_all_registers()
        ctxs.append(
            MeterCtx(
                meter_id=m.id,
                serial_number=int(m.serial_number) if str(m.serial_number).isdigit() else 0,
                username=m.username,
                password=m.password,
                driver_meter=drv,
            )
        )

    # stop check before prelogin
    if _should_stop():
        scheduler.set_prelogin_result(task_id, [])
        scheduler.set_loop_state(LoopState.STOPPED)
        scheduler.clear_loop_task()
        return "stopped"

    if not _wait_if_paused():
        scheduler.set_prelogin_result(task_id, [])
        scheduler.set_loop_state(LoopState.STOPPED)
        scheduler.clear_loop_task()
        return "stopped"

    # ---- prelogin all ----
    functional_ctxs: list[MeterCtx] = []
    for ctx in ctxs:
        if not _wait_if_paused():
            break
        if _should_stop():
            break

        sem.acquire()
        try:
            try:
                err = service.login(ctx.username, ctx.password, ctx.serial_number)
            except TimeoutError:
                logger.warning("Pre-login timeout: serial=%s", ctx.serial_number)
                continue
        finally:
            try:
                service.media.flush_input()
            except Exception:
                logger.debug("Pre-login flush failed", exc_info=True)
            sem.release()

        if err != EDMI_ERROR_CODE.NONE:
            logger.warning(
                "Pre-login failed: serial=%s err=%s",
                ctx.serial_number,
                serialize_error(err),
            )
            continue

        logger.info("Pre-login ok: serial=%s", ctx.serial_number)
        functional_ctxs.append(ctx)

    # ---- publish durable prelogin result ----
    functional_ids = [c.meter_id for c in functional_ctxs]

    scheduler.set_prelogin_result(task_id, functional_ids)

    # if nothing functional, exit (prelogin result already published)
    if not functional_ctxs:
        scheduler.clear_loop_task()
        scheduler.set_loop_state(LoopState.STOPPED)
        return "stopped"

    # ---- main loop: 30-second aligned slots; read each functional meter once per slot ----
    scheduler.set_loop_state(LoopState.RUNNING)
    while True:
        if _should_stop():
            break

        if not _wait_if_paused():
            break
        _run_once_task_if_ready()

        now = datetime.now(timezone.utc)
        slot_ts = _next_30s_boundary(now)  # exact boundary timestamp (UTC)

        # Wait (in stop-responsive chunks) until the slot boundary
        if not _sleep_until(slot_ts, max_chunk_seconds=0.2):
            break

        # Use the slot boundary timestamp for DB persistence (normalized)
        # Process meters for this slot
        for ctx in functional_ctxs:
            if not _wait_if_paused():
                break
            if _should_stop():
                break

            try:
                sem.acquire()
                try:
                    registers, err_code = service.read_all_registers_continuously(
                        ctx.username,
                        ctx.password,
                        ctx.serial_number,
                        ctx.driver_meter,
                    )
                finally:
                    sem.release()

                if err_code == EDMI_ERROR_CODE.NONE:
                    values: dict[str, Any] = map_registers_to_reading_columns(registers)

                    row = ReadingValue(
                        meter_id=ctx.meter_id,
                        time_stamp_utc=slot_ts,  # exact ..:..:00 / ..:..:30
                        **values,
                    )

                    with Session(engine) as session:
                        session.add(row)
                        session.commit()
                else:
                    logger.warning(
                        "Read failed: serial=%s err=%s",
                        ctx.serial_number,
                        serialize_error(err_code),
                    )

            except Exception as e:
                logger.exception(
                    "read_and_save_meters_loop error (serial=%s): %s",
                    ctx.serial_number,
                    e,
                )

    scheduler.set_loop_state(LoopState.STOPPED)
    scheduler.clear_loop_task()
    return "stopped"


@celery_app.task(bind=True, base=BaseTask, name="read_and_save_meters_loop_sreaming_status")
def read_and_save_meters_loop_sreaming_status(self, meter_ids) -> str:
    r = _redis()
    keys = Keys()
    task_id: str = self.request.id
    scheduler = TaskScheduler(r, keys)

    # ---- per-task prelogin state reset ----
    scheduler.clear_prelogin(task_id)
    r.delete(_meter_status_list_key(keys, task_id))
    r.delete(_meter_status_seq_key(keys, task_id))
    if scheduler.get_loop_control() == LoopControl.STOP:
        scheduler.set_prelogin_result(task_id, [])
        scheduler.set_loop_state(LoopState.STOPPED)
        scheduler.clear_loop_task()
        return "stopped"
    scheduler.force_register_loop_task(task_id, priority=0)

    service = get_meter_service()
    sem = get_bus_sem()
    engine = get_engine()

    def _should_stop() -> bool:
        return scheduler.get_loop_control() == LoopControl.STOP

    def _should_pause() -> bool:
        return scheduler.get_loop_control() == LoopControl.PAUSE

    def _run_once_task_if_ready() -> bool:
        ran_any = False
        loop_priority = scheduler.get_loop_priority()
        while True:
            task = scheduler.claim_next_task(max_priority=loop_priority)
            if not task:
                break
            ran_any = True
            scheduler.set_loop_state(LoopState.PAUSED)
            try:
                if task.get("name") == "read_profile":
                    payload = task.get("payload") or {}
                    result = _run_profile_read(
                        service=service,
                        sem=sem,
                        meter_id=payload.get("meter_id"),
                        serial_number=payload.get("serial_number"),
                        username=payload.get("username"),
                        password=payload.get("password"),
                        survey=payload.get("survey"),
                        from_datetime=payload.get("from_datetime"),
                        to_datetime=payload.get("to_datetime"),
                        max_records=payload.get("max_records"),
                    )
                    scheduler.complete_task(task["task_id"], result)
                else:
                    scheduler.fail_task(task["task_id"], "unknown_task")
            except Exception:
                logger.exception("scheduled task failed")
                scheduler.fail_task(task["task_id"], "exception")
            finally:
                if not _should_stop():
                    scheduler.set_loop_state(LoopState.RUNNING)
        return ran_any

    def _wait_if_paused() -> bool:
        if not _should_pause():
            return True
        scheduler.set_loop_state(LoopState.PAUSED)
        try:
            while _should_pause():
                if _should_stop():
                    return False
                _run_once_task_if_ready()
                time.sleep(0.2)
        finally:
            if not _should_stop():
                scheduler.set_loop_state(LoopState.RUNNING)
        return True

    def _floor_to_30s_slot(ts: datetime) -> datetime:
        # Normalize to exactly ..:..:00 or ..:..:30 (UTC)
        slot_second = 0 if ts.second < 30 else 30
        return ts.replace(second=slot_second, microsecond=0)

    def _next_30s_boundary(now: datetime) -> datetime:
        # If already exactly on a boundary, return it; otherwise return the next boundary.
        floored = _floor_to_30s_slot(now)
        if now == floored:
            return floored
        return floored + timedelta(seconds=30)

    def _sleep_until(target: datetime, max_chunk_seconds: float = 0.2) -> bool:
        # Returns False if stopped while waiting, True otherwise.
        while True:
            if _should_stop():
                return False
            if _should_pause():
                if not _wait_if_paused():
                    return False
            if scheduler.has_runnable_task(max_priority=scheduler.get_loop_priority()):
                _run_once_task_if_ready()
            now = datetime.now(timezone.utc)
            remaining = (target - now).total_seconds()
            if remaining <= 0:
                return True
            time.sleep(min(remaining, max_chunk_seconds))

    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _set_status(
        status_map: dict[int, dict[str, Any]],
        meter_id: int,
        status: str,
        error: str | None = None,
    ) -> None:
        payload = {
            "meter_id": meter_id,
            "status": status,
            "updated_at": _now_iso(),
        }
        if error:
            payload["error"] = error
        status_map[meter_id] = payload

    def _snapshot(status_map: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        return [status_map[mid] for mid in sorted(status_map.keys())]

    @dataclass(frozen=True)
    class MeterCtx:
        meter_id: int
        serial_number: int
        username: str
        password: str
        driver_meter: Any

    with Session(engine) as session:
        db_meters: list[Meter] = (
            session.query(Meter)
            .filter(Meter.id.in_(meter_ids))
            .all()
        )

    if not db_meters:
        raise ValueError("No meters registered")

    ctxs: list[MeterCtx] = []
    status_map: dict[int, dict[str, Any]] = {}
    for m in db_meters:
        drv = service.get_meter(
            serial=int(m.serial_number) if str(m.serial_number).isdigit() else 0,
            username=m.username,
            password=m.password,
        )
        drv.init_all_registers()
        ctxs.append(
            MeterCtx(
                meter_id=m.id,
                serial_number=int(m.serial_number) if str(m.serial_number).isdigit() else 0,
                username=m.username,
                password=m.password,
                driver_meter=drv,
            )
        )
        _set_status(status_map, int(m.id), "pending")

    # stop check before prelogin
    if _should_stop():
        for mid in status_map.keys():
            _set_status(status_map, mid, "stopped")
        _publish_meter_status(
            r,
            keys,
            task_id=task_id,
            meter_status=_snapshot(status_map),
        )
        scheduler.set_prelogin_result(task_id, [])
        scheduler.set_loop_state(LoopState.STOPPED)
        scheduler.clear_loop_task()
        return "stopped"

    if not _wait_if_paused():
        for mid in status_map.keys():
            _set_status(status_map, mid, "stopped")
        _publish_meter_status(
            r,
            keys,
            task_id=task_id,
            meter_status=_snapshot(status_map),
        )
        scheduler.set_prelogin_result(task_id, [])
        scheduler.set_loop_state(LoopState.STOPPED)
        scheduler.clear_loop_task()
        return "stopped"

    # ---- prelogin all ----
    functional_ctxs: list[MeterCtx] = []
    for ctx in ctxs:
        if not _wait_if_paused():
            break
        if _should_stop():
            break

        sem.acquire()
        try:
            try:
                err = service.login(ctx.username, ctx.password, ctx.serial_number)
            except TimeoutError:
                logger.warning("Pre-login timeout: serial=%s", ctx.serial_number)
                _set_status(status_map, ctx.meter_id, "prelogin_timeout")
                continue
        finally:
            try:
                service.media.flush_input()
            except Exception:
                logger.debug("Pre-login flush failed", exc_info=True)
            sem.release()

        if err != EDMI_ERROR_CODE.NONE:
            logger.warning(
                "Pre-login failed: serial=%s err=%s",
                ctx.serial_number,
                serialize_error(err),
            )
            _set_status(
                status_map,
                ctx.meter_id,
                "prelogin_failed",
                error=serialize_error(err),
            )
            continue

        logger.info("Pre-login ok: serial=%s", ctx.serial_number)
        _set_status(status_map, ctx.meter_id, "prelogin_ok")
        functional_ctxs.append(ctx)

    _publish_meter_status(
        r,
        keys,
        task_id=task_id,
        meter_status=_snapshot(status_map),
    )

    # ---- publish durable prelogin result ----
    functional_ids = [c.meter_id for c in functional_ctxs]

    scheduler.set_prelogin_result(task_id, functional_ids)

    # if nothing functional, exit (prelogin result already published)
    if not functional_ctxs:
        scheduler.set_loop_state(LoopState.STOPPED)
        scheduler.clear_loop_task()
        return "stopped"

    # ---- main loop: 30-second aligned slots; read each functional meter once per slot ----
    scheduler.set_loop_state(LoopState.RUNNING)
    while True:
        if _should_stop():
            break

        if not _wait_if_paused():
            break
        _run_once_task_if_ready()

        now = datetime.now(timezone.utc)
        slot_ts = _next_30s_boundary(now)  # exact boundary timestamp (UTC)

        # Wait (in stop-responsive chunks) until the slot boundary
        if not _sleep_until(slot_ts, max_chunk_seconds=0.2):
            break

        # Use the slot boundary timestamp for DB persistence (normalized)
        # Process meters for this slot
        for ctx in functional_ctxs:
            if not _wait_if_paused():
                break
            if _should_stop():
                break

            try:
                sem.acquire()
                try:
                    registers, err_code = service.read_all_registers_continuously(
                        ctx.username,
                        ctx.password,
                        ctx.serial_number,
                        ctx.driver_meter,
                    )
                finally:
                    sem.release()

                if err_code == EDMI_ERROR_CODE.NONE:
                    values: dict[str, Any] = map_registers_to_reading_columns(registers)

                    row = ReadingValue(
                        meter_id=ctx.meter_id,
                        time_stamp_utc=slot_ts,  # exact ..:..:00 / ..:..:30
                        **values,
                    )

                    with Session(engine) as session:
                        session.add(row)
                        session.commit()

                    _set_status(status_map, ctx.meter_id, "read_ok")
                else:
                    logger.warning(
                        "Read failed: serial=%s err=%s",
                        ctx.serial_number,
                        serialize_error(err_code),
                    )
                    _set_status(
                        status_map,
                        ctx.meter_id,
                        "read_failed",
                        error=serialize_error(err_code),
                    )

            except Exception as e:
                logger.exception(
                    "read_and_save_meters_loop_sreaming_status error (serial=%s): %s",
                    ctx.serial_number,
                    e,
                )
                _set_status(status_map, ctx.meter_id, "read_exception", error=str(e))

            _publish_meter_status(
                r,
                keys,
                task_id=task_id,
                meter_status=_snapshot(status_map),
                slot_ts=slot_ts,
            )

    for mid in status_map.keys():
        _set_status(status_map, mid, "stopped")
    _publish_meter_status(
        r,
        keys,
        task_id=task_id,
        meter_status=_snapshot(status_map),
    )

    scheduler.set_loop_state(LoopState.STOPPED)
    scheduler.clear_loop_task()
    return "stopped"


@celery_app.task(bind=True, base=BaseTask, name="test_login_meters")
def test_login_meters(self, meter_ids) -> str:
    r = _redis()
    keys = Keys()
    task_id: str = self.request.id
    scheduler = TaskScheduler(r, keys)

    scheduler.clear_prelogin(task_id)

    service = get_meter_service()
    sem = get_bus_sem()
    engine = get_engine()

    with Session(engine) as session:
        db_meters: list[Meter] = (
            session.query(Meter)
            .filter(Meter.id.in_(meter_ids))
            .all()
        )

    if not db_meters:
        raise ValueError("No meters registered")

    meters = []
    serial_to_id: dict[int, int] = {}
    for m in db_meters:
        drv = service.get_meter(
            serial=int(m.serial_number) if str(m.serial_number).isdigit() else 0,
            username=m.username,
            password=m.password,
        )
        meters.append(drv)
        serial_to_id[int(m.serial_number) if str(m.serial_number).isdigit() else 0] = int(m.id)

    sem.acquire()
    try:
        ok_serials = service.test_login_meters(meters)
    finally:
        try:
            service.media.flush_input()
        except Exception:
            logger.debug("Test-login flush failed", exc_info=True)
        sem.release()

    ok_ids: list[int] = []
    for serial in ok_serials:
        meter_id = serial_to_id.get(int(serial))
        if meter_id is not None:
            ok_ids.append(int(meter_id))


    scheduler.set_prelogin_result(task_id, ok_ids)

    return "done"


@celery_app.task(bind=True, base=BaseTask, name="read_profile_once")
def read_profile_once(
    self,
    *,
    meter_id: int,
    serial_number: int,
    username: str,
    password: str,
    survey: int,
    from_datetime: str,
    to_datetime: str,
    max_records: int | None = None,
) -> dict[str, Any]:
    r = _redis()
    keys = Keys()
    service = get_meter_service()
    sem = get_bus_sem()

    try:
        result = _run_profile_read(
            service=service,
            sem=sem,
            meter_id=meter_id,
            serial_number=serial_number,
            username=username,
            password=password,
            survey=survey,
            from_datetime=from_datetime,
            to_datetime=to_datetime,
            max_records=max_records,
        )
        return result
    except Exception:
        logger.exception("read_profile_once error: serial=%s", serial_number)
        return {
            "status": "error",
            "meter_id": meter_id,
            "survey": _survey_name(survey),
            "field": [],
            "interval_seconds": None,
            "count": 0,
            "data": [],
        }
