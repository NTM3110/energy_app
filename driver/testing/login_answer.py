#!/usr/bin/env python3
import argparse
import errno
import sys
import time
import serial


REPLY_HEX = "02 45 01 2b 16 68 0e fa aa 45 ff ff 06 ee 8c 03"


def parse_hex_bytes(s: str) -> bytes:
    s = s.replace(",", " ").strip()
    parts = [p for p in s.split() if p]
    return bytes(int(p, 16) for p in parts)



def format_hex(data: bytes) -> str:
    return " ".join(f"{b:02x}" for b in data)


def open_serial(port: str, baud: int, timeout: float) -> serial.Serial:
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baud,
            timeout=timeout,         # read timeout (seconds)
            write_timeout=timeout,   # write timeout (seconds)
        )
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        return ser

    except serial.SerialException as e:
        cause = e.__cause__ or e
        if isinstance(cause, OSError):
            if cause.errno == errno.EACCES:
                raise RuntimeError(f"Serial port '{port}' is occupied or permission denied") from e
            if cause.errno == errno.ENOENT:
                raise RuntimeError(f"Serial port '{port}' not found") from e
        raise RuntimeError(f"Failed to open serial port '{port}': {e}") from e


def read_one_message(ser: serial.Serial, overall_timeout: float) -> bytes:
    """
    Waits for the first incoming bytes, then collects bytes until the line
    stays idle for a short gap, returning the collected message.
    """
    start = time.monotonic()
    buf = bytearray()

    # Phase 1: wait for first byte(s)
    while True:
        if overall_timeout is not None and (time.monotonic() - start) >= overall_timeout:
            raise TimeoutError("Timeout waiting for first incoming data")

        n = ser.in_waiting
        chunk = ser.read(n if n > 0 else 1)
        if chunk:
            buf.extend(chunk)
            break

    # Phase 2: keep reading until idle gap
    idle_gap_s = max(ser.timeout or 0.1, 0.1)
    last_rx = time.monotonic()

    while True:
        if overall_timeout is not None and (time.monotonic() - start) >= overall_timeout:
            break

        n = ser.in_waiting
        if n > 0:
            chunk = ser.read(n)
            if chunk:
                buf.extend(chunk)
                last_rx = time.monotonic()
                continue

        if (time.monotonic() - last_rx) >= idle_gap_s:
            break

        time.sleep(0.01)

    return bytes(buf)


def main() -> int:
    ap = argparse.ArgumentParser(description="Wait for one serial message, reply, then print next reply in hex.")
    ap.add_argument("--port", required=True, help="Serial port (e.g. COM3, /dev/ttyUSB0)")
    ap.add_argument("--baud", type=int, required=True, help="Baud rate (e.g. 9600, 115200)")
    ap.add_argument("--timeout", type=float, default=20.0, help="Overall timeout seconds for each wait (default: 10)")
    ap.add_argument("--reply", default=REPLY_HEX, help="Reply bytes as hex (default is the provided frame)")
    args = ap.parse_args()

    reply_bytes = parse_hex_bytes(args.reply)

    ser = open_serial(args.port, args.baud, timeout=0.2)
    try:
        first = read_one_message(ser, overall_timeout=args.timeout)
        print(f"RX1 ({len(first)} bytes): {format_hex(first)}")

        ser.write(reply_bytes)
        ser.flush()
        print(f"TX  ({len(reply_bytes)} bytes): {format_hex(reply_bytes)}")

        second = read_one_message(ser, overall_timeout=args.timeout)
        print(f"RX2 ({len(second)} bytes): {format_hex(second)}")

    finally:
        if ser.is_open:
            ser.close()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, TimeoutError, OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
