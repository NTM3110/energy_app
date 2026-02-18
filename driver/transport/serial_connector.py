# driver/transport/serial_connector.py
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import serial
from serial import SerialException

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SerialConfig:
    port: str
    baudrate: int
    timeout_s: float
    write_timeout_s: float
    exclusive: bool = True


class SerialConnector:
    """
    Control plane (lifecycle):
      - Owns pyserial.Serial creation/close.
      - Retries connect in a background task with backoff.
      - Exposes readiness and a snapshot getter for the current Serial.

    Data plane (I/O) is handled by SerialTransport.
    """

    def __init__(self, cfg: SerialConfig) -> None:
        self._cfg = cfg
        self._ser: Optional[serial.Serial] = None

        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()

        self._task: Optional[asyncio.Task] = None

    # ----------------------------
    # Public API
    # ----------------------------

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="serial-connector")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._close_current()

    def is_ready(self) -> bool:
        return self._ready.is_set()

    async def wait_ready(self) -> None:
        await self._ready.wait()

    async def get_serial(self) -> Optional[serial.Serial]:
        async with self._lock:
            return self._ser

    async def mark_disconnected(self) -> None:
        """
        Called by data plane on I/O error to force reconnect.
        Safe to call repeatedly.
        """
        async with self._lock:
            if self._ready.is_set():
                self._ready.clear()
            await self._close_current_locked()

    # ----------------------------
    # Internals
    # ----------------------------

    async def _close_current(self) -> None:
        async with self._lock:
            await self._close_current_locked()

    async def _close_current_locked(self) -> None:
        ser = self._ser
        self._ser = None
        if ser is None:
            return
        try:
            ser.close()  # sync but cheap
        except Exception:
            pass

    async def _open_once(self) -> serial.Serial:
        def _open() -> serial.Serial:
            return serial.Serial(
                port=self._cfg.port,
                baudrate=self._cfg.baudrate,
                timeout=self._cfg.timeout_s,
                write_timeout=self._cfg.write_timeout_s,
                exclusive=self._cfg.exclusive,
            )

        return await asyncio.to_thread(_open)

    async def _set_connected(self, ser: serial.Serial) -> None:
        async with self._lock:
            # close any stale instance (defensive)
            await self._close_current_locked()
            self._ser = ser
            self._ready.set()

    async def _run(self) -> None:
        backoff_s = 0.5
        max_backoff_s = 5.0

        while not self._stop.is_set():
            if self.is_ready():
                # Data plane will call mark_disconnected() if it detects failures.
                await asyncio.sleep(0.5)
                continue

            try:
                ser = await self._open_once()
                await self._set_connected(ser)
                log.info("Serial connected: %s", self._cfg.port)
                backoff_s = 0.5

            except (FileNotFoundError, PermissionError, SerialException) as e:
                log.warning("Serial connect failed (%s). Retrying in %.1fs", e, backoff_s)
                await asyncio.sleep(backoff_s)
                backoff_s = min(max_backoff_s, backoff_s * 1.5)

            except Exception as e:
                log.exception("Unexpected serial connector error: %s", e)
                await asyncio.sleep(backoff_s)
                backoff_s = min(max_backoff_s, backoff_s * 1.5)
