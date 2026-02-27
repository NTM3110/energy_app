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
from model.models import Meter, ReadingValue, ProfileReadingValue, ProfileReadGap
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

    ctx_cache: dict[int, MeterCtx] = {}

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

        # ---- DYNAMIC METER SYNC & PRE-LOGIN ----
        with Session(engine) as session:
            db_meters = session.query(Meter).all()
        
        current_db_ids = {m.id for m in db_meters}
        for mid in list(ctx_cache.keys()):
            if mid not in current_db_ids:
                logger.info("Removing meter %s from loop", mid)
                del ctx_cache[mid]

        functional_ctxs: list[MeterCtx] = []
        for m in db_meters:
            if _should_stop() or not _wait_if_paused(): break
            
            m_ser = int(m.serial_number) if str(m.serial_number).isdigit() else 0
            if m.id not in ctx_cache or ctx_cache[m.id].username != m.username or ctx_cache[m.id].password != m.password or ctx_cache[m.id].serial_number != m_ser:
                logger.info("(Re)initializing meter %s (serial=%s)", m.id, m_ser)
                drv = service.get_meter(serial=m_ser, username=m.username, password=m.password)
                drv.init_all_registers()
                ctx_cache[m.id] = MeterCtx(m.id, m_ser, m.username, m.password, drv)
            
            ctx = ctx_cache[m.id]
            sem.acquire()
            try:
                try:
                    err = service.login(ctx.username, ctx.password, ctx.serial_number)
                except TimeoutError:
                    logger.warning("Pre-login timeout: serial=%s", ctx.serial_number)
                    continue
            finally:
                try: service.media.flush_input()
                except Exception: pass
                sem.release()

            if err == EDMI_ERROR_CODE.NONE:
                functional_ctxs.append(ctx)
            else:
                logger.warning("Pre-login failed: serial=%s err=%s", ctx.serial_number, serialize_error(err))

        scheduler.set_prelogin_result(task_id, [c.meter_id for c in functional_ctxs])
        if not functional_ctxs:
            continue

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
        
    def _floor_to_30m_slot(ts: datetime) -> datetime:
        slot_minute = 0 if ts.minute < 30 else 30
        return ts.replace(minute=slot_minute, second=0, microsecond=0)
    
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

    # Store survey requirement globally for the loop. 
    # For now we default to LS02 but this can be dynamic if passed to loop
    background_survey = "LS02"
    try:
        background_survey_enum = EDMISurvey[background_survey]
    except KeyError:
        background_survey_enum = EDMISurvey.LS02

    ctx_cache: dict[int, MeterCtx] = {}
    status_map: dict[int, dict[str, Any]] = {}

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

        # ---- DYNAMIC METER SYNC & PRE-LOGIN ----
        with Session(engine) as session:
            db_meters = session.query(Meter).all()
        
        current_db_ids = {m.id for m in db_meters}
        for mid in list(ctx_cache.keys()):
            if mid not in current_db_ids:
                logger.info("Removing meter %s from loop", mid)
                del ctx_cache[mid]
                if mid in status_map: del status_map[mid]
        
        for mid in current_db_ids:
            if mid not in status_map: _set_status(status_map, mid, "pending")

        functional_ctxs: list[MeterCtx] = []
        for m in db_meters:
            if _should_stop() or not _wait_if_paused(): break
            
            m_ser = int(m.serial_number) if str(m.serial_number).isdigit() else 0
            if m.id not in ctx_cache or ctx_cache[m.id].username != m.username or ctx_cache[m.id].password != m.password or ctx_cache[m.id].serial_number != m_ser:
                logger.info("(Re)initializing meter %s (serial=%s)", m.id, m_ser)
                drv = service.get_meter(serial=m_ser, username=m.username, password=m.password)
                drv.init_all_registers()
                ctx_cache[m.id] = MeterCtx(m.id, m_ser, m.username, m.password, drv)
            
            ctx = ctx_cache[m.id]
            sem.acquire()
            try:
                try:
                    err = service.login(ctx.username, ctx.password, ctx.serial_number)
                except TimeoutError:
                    logger.warning("Pre-login timeout: serial=%s", ctx.serial_number)
                    _set_status(status_map, ctx.meter_id, "prelogin_timeout")
                    continue
                except Exception as e:
                    logger.warning("Pre-login error: serial=%s err=%s", ctx.serial_number, e)
                    _set_status(status_map, ctx.meter_id, "prelogin_error", error=str(e))
                    continue
            finally:
                try: service.media.flush_input()
                except Exception: pass
                sem.release()

            if err == EDMI_ERROR_CODE.NONE:
                _set_status(status_map, ctx.meter_id, "prelogin_ok")
                functional_ctxs.append(ctx)
            else:
                logger.warning("Pre-login failed: serial=%s err=%s", ctx.serial_number, serialize_error(err))
                _set_status(status_map, ctx.meter_id, "prelogin_failed", error=serialize_error(err))

        _publish_meter_status(r, keys, task_id=task_id, meter_status=_snapshot(status_map))
        scheduler.set_prelogin_result(task_id, [c.meter_id for c in functional_ctxs])

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
        local_slot_ts = slot_ts.astimezone()

        current_5m_slot = _floor_to_5m_slot(local_slot_ts)
        if last_profile_read_ts is None:
            last_profile_read_ts = current_5m_slot

        if last_profile_read_ts != current_5m_slot:
            # We entered a new 30-minute slot. Execute profile reading for the previous 30 mins.
            to_dt = current_5m_slot
            from_dt = current_5m_slot - timedelta(minutes=5)
            from_str = from_dt.isoformat()
            to_str = to_dt.isoformat()

            logger.info(f"Triggering integrated profile read for slot {current_5m_slot.isoformat()}")

            # --- Record gaps for meters NOT in functional_ctxs ---
            functional_ids = {c.meter_id for c in functional_ctxs}
            non_functional_ids = current_db_ids - functional_ids
            if non_functional_ids:
                try:
                    with Session(engine) as session:
                        for nf_id in non_functional_ids:
                            gap = ProfileReadGap(
                                meter_id=nf_id,
                                from_dt=from_dt,
                                to_dt=to_dt,
                            )
                            session.add(gap)
                            try:
                                session.commit()
                            except Exception:
                                session.rollback()  # duplicate or other
                    logger.info(
                        "Recorded profile gaps for %d non-functional meter(s): %s",
                        len(non_functional_ids),
                        non_functional_ids,
                    )
                except Exception as e:
                    logger.exception("Failed to record profile gaps: %s", e)

            # --- Profile-read each functional meter ---
            successful_meter_ids: set[int] = set()
            for ctx in functional_ctxs:
                if _should_stop():
                    break
                logger.info(
                    "------------------- Profile read for meter %s, %s, %s, %s ------------------------",
                    ctx.meter_id, ctx.serial_number, from_str, to_str,
                )
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
                                    dt_val = row_data.get("DateTime")
                                    pr = ProfileReadingValue(
                                        meter_id=ctx.meter_id,
                                        time_stamp=dt_val,
                                        record_status=row_data.get("Record Status"),
                                        total_energy_tot_imp_wh=row_data.get("Total Energy Tot IMP Wh @"),
                                        total_energy_tot_exp_wh=row_data.get("Total Energy Tot EXP Wh @"),
                                        total_energy_tot_imp_va=row_data.get("Total Energy Tot IMP va @"),
                                        total_energy_tot_exp_va=row_data.get("Total Energy Tot EXP va @"),
                                    )
                                    session.add(pr)
                                    try:
                                        session.commit()
                                    except Exception:
                                        session.rollback()
                            logger.info(
                                "Integrated loop saved %d profile records for meter %s",
                                len(records), ctx.meter_id,
                            )
                        except Exception as e:
                            logger.exception("Failed to save background profile data: %s", e)
                        successful_meter_ids.add(ctx.meter_id)
                    else:
                        # Profile read returned non-ok — record a gap
                        try:
                            with Session(engine) as session:
                                gap = ProfileReadGap(
                                    meter_id=ctx.meter_id,
                                    from_dt=from_dt,
                                    to_dt=to_dt,
                                )
                                session.add(gap)
                                try:
                                    session.commit()
                                except Exception:
                                    session.rollback()
                            logger.warning(
                                "Profile read non-ok for meter %s — gap recorded",
                                ctx.meter_id,
                            )
                        except Exception as e:
                            logger.exception("Failed to record gap for meter %s: %s", ctx.meter_id, e)

                except Exception as e:
                    logger.exception("Integrated profile read error: %s", e)
                    # Record gap for exception too
                    try:
                        with Session(engine) as session:
                            gap = ProfileReadGap(
                                meter_id=ctx.meter_id,
                                from_dt=from_dt,
                                to_dt=to_dt,
                            )
                            session.add(gap)
                            try:
                                session.commit()
                            except Exception:
                                session.rollback()
                    except Exception:
                        pass

            # --- Retry pending gaps for meters that read successfully ---
            if successful_meter_ids:
                try:
                    with Session(engine) as session:
                        pending_gaps = (
                            session.query(ProfileReadGap)
                            .filter(
                                ProfileReadGap.meter_id.in_(successful_meter_ids),
                                ProfileReadGap.status == "pending",
                                ProfileReadGap.retry_count < 3,
                            )
                            .order_by(ProfileReadGap.from_dt)
                            .limit(10)  # cap per cycle to avoid overload
                            .all()
                        )

                    for gap in pending_gaps:
                        if _should_stop():
                            break
                        # Find the ctx for this meter
                        gap_ctx = next(
                            (c for c in functional_ctxs if c.meter_id == gap.meter_id),
                            None,
                        )
                        if gap_ctx is None:
                            continue

                        logger.info(
                            "Retrying gap meter=%s from=%s to=%s (attempt %d)",
                            gap.meter_id, gap.from_dt.isoformat(),
                            gap.to_dt.isoformat(), gap.retry_count + 1,
                        )
                        try:
                            p_result = _run_profile_read(
                                service=service,
                                sem=sem,
                                meter_id=gap_ctx.meter_id,
                                serial_number=gap_ctx.serial_number,
                                username=gap_ctx.username,
                                password=gap_ctx.password,
                                survey=int(background_survey_enum),
                                from_datetime=gap.from_dt.isoformat(),
                                to_datetime=gap.to_dt.isoformat(),
                                max_records=5,
                            )

                            with Session(engine) as session:
                                db_gap = session.get(ProfileReadGap, gap.id)
                                if p_result and p_result.get("status") == "ok":
                                    records = p_result.get("data", [])
                                    for row_data in records:
                                        dt_val = row_data.get("DateTime")
                                        pr = ProfileReadingValue(
                                            meter_id=gap_ctx.meter_id,
                                            time_stamp=dt_val,
                                            record_status=row_data.get("Record Status"),
                                            total_energy_tot_imp_wh=row_data.get("Total Energy Tot IMP Wh @"),
                                            total_energy_tot_exp_wh=row_data.get("Total Energy Tot EXP Wh @"),
                                            total_energy_tot_imp_va=row_data.get("Total Energy Tot IMP va @"),
                                            total_energy_tot_exp_va=row_data.get("Total Energy Tot EXP va @"),
                                        )
                                        session.add(pr)
                                        try:
                                            session.commit()
                                        except Exception:
                                            session.rollback()
                                    db_gap.status = "done"
                                    logger.info(
                                        "Gap retry OK: meter=%s from=%s — saved %d records",
                                        gap.meter_id, gap.from_dt.isoformat(), len(records),
                                    )
                                else:
                                    db_gap.retry_count += 1
                                    if db_gap.retry_count >= 3:
                                        db_gap.status = "failed"
                                        logger.warning(
                                            "Gap retry exhausted (3/3): meter=%s from=%s",
                                            gap.meter_id, gap.from_dt.isoformat(),
                                        )
                                    else:
                                        logger.warning(
                                            "Gap retry %d/3 failed: meter=%s from=%s",
                                            db_gap.retry_count, gap.meter_id,
                                            gap.from_dt.isoformat(),
                                        )
                                session.commit()

                        except Exception as e:
                            logger.exception(
                                "Gap retry exception: meter=%s from=%s: %s",
                                gap.meter_id, gap.from_dt.isoformat(), e,
                            )
                            try:
                                with Session(engine) as session:
                                    db_gap = session.get(ProfileReadGap, gap.id)
                                    db_gap.retry_count += 1
                                    if db_gap.retry_count >= 3:
                                        db_gap.status = "failed"
                                    session.commit()
                            except Exception:
                                pass

                except Exception as e:
                    logger.exception("Failed to process pending gaps: %s", e)

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
