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
    #If there is flag to stop then stop the loop
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
        
    def _floor_to_5m_slot(ts: datetime) -> datetime:
        slot_minute = (ts.minute // 5) * 5
        return ts.replace(minute=slot_minute, second=0, microsecond=0)

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
    
    # Store survey requirement globally for the loop. 
    # For now we default to LS02 but this can be dynamic if passed to loop
    background_survey = "LS02"
    try:
        background_survey_enum = EDMISurvey[background_survey]
    except KeyError:
        background_survey_enum = EDMISurvey.LS02
    
    #List all the meters available and init register for each meter
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
    last_profile_read_ts: datetime | None = None
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
                
        # ---- START INTEGRATED PROFILE READ CHECK ----
        # See if we crossed a 5-minute profile read boundary

        print("---------------- START INTEGRATED PROFILE READ CHECK ------------------")
        local_slot_ts = slot_ts.astimezone()
        print("slot_ts", local_slot_ts)

        current_5m_slot = _floor_to_5m_slot(local_slot_ts)
        if last_profile_read_ts is None:
            last_profile_read_ts = current_5m_slot

        if last_profile_read_ts != current_5m_slot:
            # We entered a new 5-minute slot. Execute profile reading for the previous 5 mins.
            try:
                from model.models import ProfileReadingValue
                logger.info(f"Triggering integrated profile read for slot {current_5m_slot.isoformat()}")
                for ctx in functional_ctxs:
                    if _should_stop():
                        break
                    
                    to_dt = current_5m_slot
                    from_dt = current_5m_slot - timedelta(minutes=5)
                    from_str = from_dt.isoformat()
                    to_str = to_dt.isoformat()
                    
                    try:
                        p_result = _run_profile_read(
                            service=service,
                            sem=sem,
                            meter_id=ctx.meter_id,
                            serial_number=ctx.serial_number,
                            username=ctx.username,
                            password=ctx.password,
                            survey=int(background_survey_enum),
                            from_datetime=from_str,
                            to_datetime=to_str,
                            max_records=5,
                        )

                        if p_result and p_result.get("status") == "ok":
                            records = p_result.get("data", [])
                            try:
                                with Session(engine) as session:
                                    for row_data in records:
                                        # Use the synchronized loop slot timestamp instead of the raw meter timestamp
                                        # to ensure consistency with register reading (+07 alignment)
                                        dt_val = row_data.get("DateTime")


                                        pr = ProfileReadingValue(
                                            meter_id=ctx.meter_id,
                                            time_stamp=dt_val,
                                            record_status=row_data.get("Record Status"),
                                            total_energy_tot_imp_wh=row_data.get("Total Energy Tot IMP Wh @"),
                                            total_energy_tot_exp_wh=row_data.get("Total Energy Tot EXP Wh @"),
                                            total_energy_tot_imp_va=row_data.get("Total Energy Tot IMP va @"),
                                            total_energy_tot_exp_va=row_data.get("Total Energy Tot EXP va @")
                                        )
                                        session.add(pr)
                                        try:
                                            session.commit()
                                        except Exception:
                                            session.rollback()
                                logger.info(f"Integrated loop saved {len(records)} profile records for meter {ctx.meter_id}")
                            except Exception as e:
                                logger.exception("Failed to save background profile data: %s", e)
                    except Exception as e:
                        logger.exception("Integrated profile read error: %s", e)
            except ImportError:
                pass
            
            # Update our marker so we don't read this slot again
            last_profile_read_ts = current_5m_slot
        # ---- END INTEGRATED PROFILE READ CHECK ----

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


@celery_app.task(bind=True, base=BaseTask, name="read_and_save_profile_loop_streaming_status")
def read_and_save_profile_loop_streaming_status(self, meter_ids, survey: str = "LS02") -> str:
    r = _redis()
    keys = Keys()
    task_id: str = self.request.id
    scheduler = TaskScheduler(r, keys, loop_name="profile")

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
                # We reuse the core read_profile logic from existing single-shot if needed
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
                logger.exception("scheduled profile task failed")
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

    def _floor_to_5m_slot(ts: datetime) -> datetime:
        # Normalize to exactly XX:00:00, XX:05:00, XX:10:00, etc. (UTC)
        slot_minute = (ts.minute // 5) * 5
        return ts.replace(minute=slot_minute, second=0, microsecond=0)

    def _next_5m_boundary(now: datetime) -> datetime:
        # If already exactly on a boundary, return it; otherwise return next boundary.
        floored = _floor_to_5m_slot(now)
        if now == floored:
            return floored
        return floored + timedelta(minutes=5)

    def _sleep_until(target: datetime, max_chunk_seconds: float = 0.5) -> bool:
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

    with Session(engine) as session:
        db_meters: list[Meter] = (
            session.query(Meter)
            .filter(Meter.id.in_(meter_ids))
            .all()
        )

    if not db_meters:
        raise ValueError("No meters registered for profile loop")

    ctxs: list[MeterCtx] = []
    status_map: dict[int, dict[str, Any]] = {}
    for m in db_meters:
        ctxs.append(
            MeterCtx(
                meter_id=m.id,
                serial_number=int(m.serial_number) if str(m.serial_number).isdigit() else 0,
                username=m.username,
                password=m.password,
            )
        )
        _set_status(status_map, m.id, "pending")

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
                logger.warning("Profile pre-login timeout: serial=%s", ctx.serial_number)
                _set_status(status_map, ctx.meter_id, "prelogin_timeout")
                continue
        finally:
            try:
                service.media.flush_input()
            except Exception:
                pass
            sem.release()

        if err != EDMI_ERROR_CODE.NONE:
            logger.warning(
                "Profile pre-login failed: serial=%s err=%s",
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

        _set_status(status_map, ctx.meter_id, "prelogin_ok")
        functional_ctxs.append(ctx)

    _publish_meter_status(
        r,
        keys,
        task_id=task_id,
        meter_status=_snapshot(status_map),
    )

    functional_ids = [c.meter_id for c in functional_ctxs]
    scheduler.set_prelogin_result(task_id, functional_ids)

    if not functional_ctxs:
        scheduler.set_loop_state(LoopState.STOPPED)
        scheduler.clear_loop_task()
        return "stopped"

    # Convert survey string to EDMISurvey Enum
    try:
        survey_enum = EDMISurvey[survey]
    except KeyError:
        logger.error("Invalid survey type: %s", survey)
        scheduler.set_loop_state(LoopState.STOPPED)
        scheduler.clear_loop_task()
        return "failed"

    from model.models import ProfileReadingValue

    # ---- main loop: 5-minute aligned slots ----
    scheduler.set_loop_state(LoopState.RUNNING)
    while True:
        if _should_stop():
            break

        if not _wait_if_paused():
            break
        _run_once_task_if_ready()

        now = datetime.now(timezone.utc)
        target_slot_ts = _next_5m_boundary(now)
        
        logger.info(f"Profile loop sleeping until {target_slot_ts.isoformat()}")

        if not _sleep_until(target_slot_ts, max_chunk_seconds=0.5):
            break

        logger.info(f"Profile loop woke up at {datetime.now(timezone.utc).isoformat()} to read slot {target_slot_ts.isoformat()}")


        # Woke up at target_slot_ts, read profile for the last 5 mins:
        target_slot_ts_local = target_slot_ts.astimezone()
        to_dt = target_slot_ts_local
        from_dt = target_slot_ts_local - timedelta(minutes=5)
        
        # Format datetimes as string for _run_profile_read
        from_str = from_dt.isoformat()
        to_str = to_dt.isoformat()

        for ctx in functional_ctxs:
            if not _wait_if_paused():
                break
            if _should_stop():
                break

            try:
                result = _run_profile_read(
                    service=service,
                    sem=sem,
                    meter_id=ctx.meter_id,
                    serial_number=ctx.serial_number,
                    username=ctx.username,
                    password=ctx.password,
                    survey=int(survey_enum),
                    from_datetime=from_str,
                    to_datetime=to_str,
                    max_records=5,
                )

                if result.get("status") == "ok":
                    records = result.get("data", [])
                    try:
                        with Session(engine) as session:
                            for row_data in records:
                                record_ts = row_data.get("time_stamp")
                                if not record_ts:
                                    continue
                                # parse record time back to datetime if needed
                                dt_val = datetime.fromisoformat(record_ts) if isinstance(record_ts, str) else record_ts

                                # Save exactly to meter_profile (ProfileReadingValue)
                                pr = ProfileReadingValue(
                                    meter_id=ctx.meter_id,
                                    time_stamp=dt_val,
                                    record_status=row_data.get("Record Status"),
                                    total_energy_tot_imp_wh=row_data.get("Total Energy Tot IMP Wh @"),
                                    total_energy_tot_exp_wh=row_data.get("Total Energy Tot EXP Wh @"),
                                    total_energy_tot_imp_va=row_data.get("Total Energy Tot IMP va @"),
                                    total_energy_tot_exp_va=row_data.get("Total Energy Tot EXP va @")
                                )
                                session.add(pr)
                                
                                # Ignore conflicts if record already exists 
                                # No bulk update, straightforward add/commit or suppress uq integrity error:
                                try:
                                    session.commit()
                                except Exception as e:
                                    session.rollback()

                        _set_status(status_map, ctx.meter_id, "read_ok")
                        logger.info(f"Successfully saved {len(records)} profile records for meter {ctx.meter_id}")
                    except Exception as e:
                        logger.exception("Failed to save profile: %s", e)
                        _set_status(status_map, ctx.meter_id, "read_exception", error=str(e))
                else:
                    _set_status(
                        status_map,
                        ctx.meter_id,
                        "read_failed",
                        error="profile_read_error",
                    )

            except Exception as e:
                logger.exception("read profile streaming loop error: %s", e)
                _set_status(status_map, ctx.meter_id, "read_exception", error=str(e))

            _publish_meter_status(
                r,
                keys,
                task_id=task_id,
                meter_status=_snapshot(status_map),
                slot_ts=target_slot_ts,
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
