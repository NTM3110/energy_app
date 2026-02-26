from __future__ import annotations

import logging
import struct
from typing import Union
import binascii
from driver.utils import as_bytes

from driver.edmi_enums import (
    EDMI_STX_IDEN,
    EDMI_E_FRAME_IDEN,
    EDMI_CLIENT_SERIAL,
    EDMI_CLIENT_SERIAL_LENGTH,
    EDMI_COMMAND_TYPE,
    EDMI_COMMAND_EXTENSION,
    EDMI_ERROR_CODE
)

from driver.edmi_enums import (
    EDMI_STX_IDEN, EDMI_ETX_IDEN, EDMI_DLE_IDEN, EDMI_XON_IDEN, EDMI_XOFF_IDEN, EDMI_IDEN_CORRECTOR
)

ESCAPE_SET = {
    EDMI_STX_IDEN,
    EDMI_ETX_IDEN,
    EDMI_XON_IDEN,
    EDMI_XOFF_IDEN,
    EDMI_DLE_IDEN,
}

log = logging.getLogger(__name__)
BytesLike = Union[bytes, bytearray, memoryview]

def wake_up_seq() -> bytes:
    return b"/?!\r\n"

def edmi_post_process(packet: BytesLike) -> bytes:

    mv = packet if isinstance(packet, memoryview) else memoryview(packet)

    n = len(mv)
    if n == 0:
        return b""
    if mv[0] != EDMI_STX_IDEN:
        raise ValueError("packet must start with STX")

    # Worst-case expansion: every byte after STX becomes 2 bytes (DLE + corrected)
    # Output length <= 1 + 2*(n-1) = 2n-1
    out = bytearray(2 * n - 1)
    o = 0

    # Copy STX as-is
    out[o] = mv[0]
    o += 1

    for b in mv[1:]:
        if b in ESCAPE_SET:
            out[o] = EDMI_DLE_IDEN
            out[o + 1] = (b + EDMI_IDEN_CORRECTOR) & 0xFF
            o += 2
        else:
            out[o] = b
            o += 1
    return bytes(out[:o])

def edmi_pre_process(packet: BytesLike) -> bytes:
    """
    Reverse of edmi_post_process:
    - If a DLE byte is seen, consume next byte and output (next - 0x40).
    - Otherwise output the byte as-is.
    """
    mv = packet if isinstance(packet, memoryview) else memoryview(packet)
    n = mv.nbytes
    if n == 0:
        return b""

    out = bytearray(n)  # output never longer than input
    out_mv = memoryview(out)
    o = 0
    i = 0

    dle = EDMI_DLE_IDEN
    corr = EDMI_IDEN_CORRECTOR

    while i < n:
        b = mv[i]
        if b == dle:
            i += 1
            if i >= n:
                raise ValueError("truncated escape (DLE at end)")
            out_mv[o] = (mv[i] - corr) & 0xFF
            o += 1
            i += 1
        else:
            out_mv[o] = b
            o += 1
            i += 1

    return out_mv[:o].tobytes()



def edmi_validate_crc(frame: BytesLike) -> EDMI_ERROR_CODE:
    """
    Validate CRC of a pre-processed EDMI frame.

    Input:
        frame = STX ... payload ... CRC(2) ETX
        (byte-stuffing already removed)

    Behavior:
        - Verifies STX / ETX
        - Computes CRC over STX .. payload
        - Compares with received CRC
        - Does NOT modify or strip data

    Returns:
        EDMI_ERROR_CODE.NONE on success
        EDMI_ERROR_CODE.RESPONSE_WRONG_LENGTH
        EDMI_ERROR_CODE.RESPONSE_CRC_ERROR
    """
    mv = frame if isinstance(frame, memoryview) else memoryview(frame)

    # Need at least: STX + CRC(2) + ETX
    if mv.nbytes < 4:
        return EDMI_ERROR_CODE.RESPONSE_WRONG_LENGTH

    if mv[0] != EDMI_STX_IDEN or mv[-1] != EDMI_ETX_IDEN:
        return EDMI_ERROR_CODE.RESPONSE_WRONG_LENGTH

    # Data over which CRC is calculated: STX .. payload (exclude CRC and ETX)
    data = mv[:-3]

    # Received CRC is the two bytes before ETX (big-endian)
    recv_crc = (mv[-3] << 8) | mv[-2]

    calc_crc = binascii.crc_hqx(data, 0) & 0xFFFF

    if calc_crc != recv_crc:
        return EDMI_ERROR_CODE.RESPONSE_CRC_ERROR

    return EDMI_ERROR_CODE.NONE
    
def edmi_begin_init_packet(
    serial: int,
    command_type: EDMI_COMMAND_TYPE,
    command_extension: EDMI_COMMAND_EXTENSION = EDMI_COMMAND_EXTENSION.NO_EXTENSION,
) -> bytes:
    """
        STX
        E_FRAME
        serial (u32)
        client_serial (6 bytes)
        command_type
        optional command_extension if != NO_EXTENSION
    """
    if not (0 <= serial <= 0xFFFFFFFF):
        raise ValueError("serial must fit in uint32")

    include_ext = command_extension != EDMI_COMMAND_EXTENSION.NO_EXTENSION
    total_len = 1 + 1 + 4 + EDMI_CLIENT_SERIAL_LENGTH + 1 + (1 if include_ext else 0)

    buf = bytearray(total_len)
    mv = memoryview(buf)
    i = 0

    # WriteChar: 1 byte each
    mv[i] = EDMI_STX_IDEN; i += 1
    mv[i] = EDMI_E_FRAME_IDEN; i += 1

    # Your transport uses big-endian for length; mirror that for u32 unless EDMI spec says otherwise.
    struct.pack_into(">I", mv, i, serial)
    i += 4

    mv[i:i + EDMI_CLIENT_SERIAL_LENGTH] = EDMI_CLIENT_SERIAL
    i += EDMI_CLIENT_SERIAL_LENGTH

    mv[i] = int(command_type) & 0xFF
    i += 1

    if include_ext:
        mv[i] = int(command_extension) & 0xFF
        i += 1

    return bytes(buf)


def edmi_end_init_packet(packet: BytesLike) -> bytes:
    mv = packet if isinstance(packet, memoryview) else memoryview(packet)
    n = len(mv)

    # Compute CRC over current packet (init=0), returns int
    crc = binascii.crc_hqx(mv.tobytes() if not mv.contiguous else mv, 0) & 0xFFFF

    # Append CRC (big-endian) using memory writes
    with_crc = bytearray(n + 2)
    out_mv = memoryview(with_crc)
    out_mv[:n] = mv
    out_mv[n] = (crc >> 8) & 0xFF
    out_mv[n + 1] = crc & 0xFF
    # Post process (byte stuffing)
    stuffed = edmi_post_process(out_mv)

    # Append ETX
    stuffed_mv = stuffed if isinstance(stuffed, memoryview) else memoryview(stuffed)
    m = len(stuffed_mv)
    final = bytearray(m + 1)
    final_mv = memoryview(final)
    final_mv[:m] = stuffed_mv
    final_mv[m] = EDMI_ETX_IDEN

    return bytes(final_mv)