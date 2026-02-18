# driver/transport/serial_transport.py
from __future__ import annotations

import asyncio
import logging
import struct
from typing import Optional

import serial

from driver.edmi_enums import EDMI_DLE_IDEN, EDMI_ETX_IDEN, EDMI_STX_IDEN
from driver.serial_settings import MAX_PACKET_LENGTH
from driver.transport.serial_connector import SerialConnector

log = logging.getLogger(__name__)


class SerialNotReadyError(ConnectionError):
    """Raised when serial is not connected/ready."""


class SerialTransport:
    """
    Data plane (I/O + framing):
      - Depends on SerialConnector for an active serial instance.
      - Runs blocking pyserial I/O in threads (asyncio.to_thread).
      - Detects disconnects via I/O exceptions/timeouts and signals connector.mark_disconnected().
      - Provides TVL and EDMI framed reads.

    Concurrency:
      - Transport is single-in-flight via an internal asyncio.Lock to prevent interleaved frames.
    """

    def __init__(self, connector: SerialConnector) -> None:
        self._connector = connector
        self._io_lock = asyncio.Lock()

    # ----------------------------
    # Readiness
    # ----------------------------

    def is_ready(self) -> bool:
        return self._connector.is_ready()

    async def wait_ready(self) -> None:
        await self._connector.wait_ready()

    # ----------------------------
    # Public I/O
    # ----------------------------

    async def write_packet(self, payload: bytes) -> None:
        self._validate_payload(payload)

        async with self._io_lock:
            ser = await self._get_ready_serial()
            try:
                await asyncio.to_thread(ser.write, payload)
            except serial.SerialTimeoutException as e:
                await self._connector.mark_disconnected()
                raise TimeoutError("serial write timeout") from e
            except (serial.SerialException, OSError) as e:
                await self._connector.mark_disconnected()
                raise OSError("serial write failed") from e

    async def read_tvl_packet(self) -> bytes:
        async with self._io_lock:
            ser = await self._get_ready_serial()
            try:
                header = await self._read_exact(ser, 2)
                (length,) = struct.unpack(">H", header)
                if length == 0:
                    return b""
                return await self._read_exact(ser, length)
            except TimeoutError:
                # await self._connector.mark_disconnected()
                raise
            except (serial.SerialException, OSError) as e:
                await self._connector.mark_disconnected()
                raise OSError("serial read failed") from e

    async def read_edmi_packet(self) -> bytes:
        async with self._io_lock:
            ser = await self._get_ready_serial()
            try:
                return await asyncio.to_thread(self._read_edmi_packet_sync, ser)
            except TimeoutError:
                # await self._connector.mark_disconnected()
                raise
            except (serial.SerialException, OSError) as e:
                await self._connector.mark_disconnected()
                raise OSError("serial read failed") from e

    async def flush_input(self) -> None:
        # Resetting the buffer can raise I/O errors on disconnect; skip to avoid
        # disrupting reconnect loops.
        return

    # ----------------------------
    # Internals
    # ----------------------------

    @staticmethod
    def _validate_payload(payload: bytes) -> None:
        if len(payload) > MAX_PACKET_LENGTH:
            raise ValueError("payload too large")

    async def _get_ready_serial(self) -> serial.Serial:
        """
        Non-blocking policy for server functionality:
          - If not ready, raise immediately.
          - This keeps API responsive when serial is unplugged.
        """
        if not self._connector.is_ready():
            raise SerialNotReadyError("serial not connected")

        ser = await self._connector.get_serial()
        if ser is None or not getattr(ser, "is_open", False):
            # treat as disconnected and let connector loop retry
            await self._connector.mark_disconnected()
            raise SerialNotReadyError("serial not connected")

        return ser

    @staticmethod
    async def _read_exact(ser: serial.Serial, n: int) -> bytes:
        buf = bytearray(n)
        mv = memoryview(buf)
        read = 0

        while read < n:
            try:
                chunk = await asyncio.to_thread(ser.read, n - read)
            except (serial.SerialException, OSError) as e:
                raise OSError("serial read failed") from e

            if not chunk:
                raise TimeoutError("serial read timeout")

            mv[read : read + len(chunk)] = chunk
            read += len(chunk)

        return bytes(buf)

    @staticmethod
    def _read_edmi_packet_sync(ser: serial.Serial) -> bytes:
        buf = bytearray()
        in_frame = False

        while True:
            n = getattr(ser, "in_waiting", 0)
            chunk = ser.read(n if n > 0 else 1)

            if not chunk:
                raise TimeoutError("serial read timeout")

            if not in_frame:
                pos = chunk.find(bytes((EDMI_STX_IDEN,)))
                if pos < 0:
                    continue
                in_frame = True
                buf.extend(chunk[pos:])
            else:
                buf.extend(chunk)

            for i in range(1, len(buf)):
                if buf[i] == EDMI_ETX_IDEN and buf[i - 1] != EDMI_DLE_IDEN:
                    return bytes(buf[: i + 1])
