# background_service/serial_owner.py
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Optional

from driver.serial_settings import BAUD, PORT, TIMEOUT_S
from driver.transport.serial_connector import SerialConfig, SerialConnector
from driver.transport.serial_transport import SerialTransport
from driver.interface.media import Media
from service.meter_service import MeterService

from background_service.providers import init_meter_service


@dataclass(frozen=True)
class _LoopThread:
    loop: asyncio.AbstractEventLoop
    thread: threading.Thread


_state_lock = threading.Lock()
_loop_thread: Optional[_LoopThread] = None
_connector: Optional[SerialConnector] = None


def _loop_main(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _ensure_loop_thread() -> _LoopThread:
    global _loop_thread
    with _state_lock:
        if _loop_thread is not None:
            return _loop_thread

        loop = asyncio.new_event_loop()
        t = threading.Thread(
            target=_loop_main,
            args=(loop,),
            name="celery-serial-asyncio-loop",
            daemon=True,
        )
        t.start()

        _loop_thread = _LoopThread(loop=loop, thread=t)
        return _loop_thread


def start_serial_owner() -> None:
    """
    Initialize SerialConnector (with reconnect loop), SerialTransport, Media, and MeterService
    inside the Celery worker process, and publish the service via providers.init_meter_service().

    Idempotent: safe to call multiple times in the same worker process.
    """
    global _connector

    lt = _ensure_loop_thread()

    with _state_lock:
        if _connector is not None:
            return

        cfg = SerialConfig(
            port=PORT,
            baudrate=BAUD,
            timeout_s=TIMEOUT_S,
            write_timeout_s=TIMEOUT_S,
            exclusive=True,
        )
        connector = SerialConnector(cfg)

        # IMPORTANT: connector.start() must execute on the loop thread, because it calls asyncio.create_task().
        def _start() -> None:
            connector.start()

        lt.loop.call_soon_threadsafe(_start)

        transport = SerialTransport(connector=connector)
        media = Media(serial_transport=transport)
        service = MeterService(media=media)

        init_meter_service(service)
        _connector = connector


def stop_serial_owner() -> None:
    """
    Best-effort stop for SerialConnector and loop thread.
    Not strictly required for normal worker exit, but keeps shutdown clean.
    """
    global _connector, _loop_thread

    with _state_lock:
        connector = _connector
        lt = _loop_thread
        _connector = None
        _loop_thread = None

    if connector is not None and lt is not None:
        fut = asyncio.run_coroutine_threadsafe(connector.stop(), lt.loop)
        try:
            fut.result(timeout=3.0)
        except Exception:
            pass

    if lt is not None:
        lt.loop.call_soon_threadsafe(lt.loop.stop)
