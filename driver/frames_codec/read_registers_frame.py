from __future__ import annotations

import struct
import logging
from typing import Union, Sequence, Union, Any, Iterable, List, Callable
import binascii
from driver.utils import as_bytes
from driver.interface.edmi_structs import EDMIRegister

from driver.edmi_enums import (
    EDMI_STX_IDEN,
    EDMI_E_FRAME_IDEN,
    EDMI_CLIENT_SERIAL,
    EDMI_CLIENT_SERIAL_LENGTH,
    EDMI_COMMAND_TYPE,
    EDMI_COMMAND_EXTENSION,
    EDMI_ERROR_CODE,
    EDMI_RESPONSE_CODE,
    EDMI_TYPE
)

from driver.edmi_enums import (
    EDMI_STX_IDEN, EDMI_ETX_IDEN, EDMI_DLE_IDEN, EDMI_XON_IDEN, \
    EDMI_XOFF_IDEN, EDMI_IDEN_CORRECTOR, EDMI_MULTI_ERR_IDEN
)
from driver.frames_codec.generics import edmi_post_process, edmi_begin_init_packet, edmi_end_init_packet,\
    edmi_pre_process, edmi_validate_crc

ESCAPE_SET = {
    EDMI_STX_IDEN,
    EDMI_ETX_IDEN,
    EDMI_XON_IDEN,
    EDMI_XOFF_IDEN,
    EDMI_DLE_IDEN,
}


BytesLike = Union[bytes, bytearray, memoryview]

_U16_BE = struct.Struct(">H")
_I16_BE = struct.Struct(">h")
_U32_BE = struct.Struct(">I")
_I32_BE = struct.Struct(">i")
_I64_BE = struct.Struct(">q")

logger = logging.getLogger(__name__)

def edmi_create_read_registers_packet(serial: int, regs: Sequence[int]) -> bytes:
    base = edmi_begin_init_packet(
        serial=serial,
        command_type=EDMI_COMMAND_TYPE.READ_REGISTER_EXTENDED,
        command_extension=EDMI_COMMAND_EXTENSION.NO_EXTENSION,
    )

    regs_count = len(regs)
    payload_len = 4 + (4 * regs_count)
    total = len(base) + payload_len

    buf = bytearray(total)
    mv = memoryview(buf)

    mv[:len(base)] = base
    i = len(base)

    _U32_BE.pack_into(mv, i, EDMI_MULTI_ERR_IDEN & 0xFFFFFFFF)
    i += 4

    for addr in regs:
        _U32_BE.pack_into(mv, i, int(addr) & 0xFFFFFFFF)
        i += 4

    return edmi_end_init_packet(mv)

# def edmi_parse_read_registers_answer(
#     payload: bytes | memoryview,
#     regs: Sequence[EDMIRegister]
# ) -> EDMI_ERROR_CODE:

#     mv = payload if isinstance(payload, memoryview) else memoryview(payload)

#     if mv.nbytes < 13:
#         return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH

#     if mv[12] != EDMI_COMMAND_TYPE.READ_REGISTER_EXTENDED:
#         return EDMI_ERROR_CODE.REQUEST_RESPONSE_COMMAND_MISMATCH

#     miden = int.from_bytes(mv[13:17], "big")
#     if miden != EDMI_MULTI_ERR_IDEN:
#         return EDMI_ERROR_CODE.REQUEST_RESPONSE_COMMAND_MISMATCH

#     idx = 17

#     for reg in regs:
#         # 1. Read error byte
#         reg.ErrorCode = mv[idx]
#         idx += 1
#         # else:
#         #     return EDMI_ERROR_CODE.UNIMPLEMENTED_DATA_TYPE
#         value_len = reg.ValueLen
#         if reg.ErrorCode == EDMI_ERROR_CODE.NONE:
#             if idx + value_len > mv.nbytes:
#                 return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
            
#             elif reg.Type == EDMI_TYPE.DATE:
#                 reg.Value = parse_date(mv[idx:idx+value_len])
#                 idx += value_len 

#             elif reg.Type == EDMI_TYPE.TIME:
#                 reg.Value = parse_time(mv[idx:idx+value_len])
#                 idx += value_len 

#             elif reg.Type == EDMI_TYPE.DATE_TIME:
#                 reg.Value = parse_datetime(mv[idx:idx+value_len])
#                 idx += value_len 

#             elif reg.Type == EDMI_TYPE.SERIAL_NUMBER:
#                 reg.Value = parse_serial_number(mv[idx:idx+value_len])
#                 idx += value_len 
#             elif reg.Type == EDMI_TYPE.DOUBLE:
#                 reg.Value = struct.unpack(
#                 ">d",
#                 mv[idx:idx + value_len]
#                 )[0]
#                 idx += value_len

#             else:
#                 reg.Value = struct.unpack(
#                     ">f",
#                     mv[idx:idx + value_len]
#                 )[0]
#                 idx += value_len
#         else:
#             reg.Value = None
#             idx += value_len  # still advance to keep alignment

#     return EDMI_ERROR_CODE.NONE

def parse_date(mv: memoryview) -> tuple:
    """
    EDMI DATE:
      byte 0 -> Day
      byte 1 -> Month
      byte 2 -> Year (00–99)
    """
    day = mv[0]
    month = mv[1]
    year = mv[2]

    return (day, month, year)

def parse_time(mv: memoryview) -> tuple:
    """
    EDMI TIME:
      byte 0 -> Hour
      byte 1 -> Minute
      byte 2 -> Second
    """
    hour = mv[0]
    minute = mv[1]
    second = mv[2]

    return (hour, minute, second)

def parse_datetime(mv: memoryview) -> tuple:
    """
    EDMI DATE_TIME:
      Day, Month, Year, Hour, Minute, Second
    """
    return (
        mv[0], mv[1], mv[2],
        mv[3], mv[4], mv[5],
    )

def parse_serial_number(mv: memoryview) -> str:
    """
    EDMI ASCII serial number (exactly 11 bytes)
    """
    if mv.nbytes < 10:
        raise ValueError("Not receiving 10 bytes for serial number. data corrupted or model has changed")
    return mv[0:9].tobytes().decode("ascii")

def parse_null_terminated_string(mv: memoryview) -> str:
    raw = mv.tobytes()
    raw = raw.split(b"\x00", 1)[0]   # stop at terminator
    return raw.decode("ascii", "strict")
def parse_error(mv: memoryview) -> str:
    return mv[0:16].tobytes().decode("ascii")

# Precompile formats (avoids rebuilding format strings each iteration)
_FLOAT_BE = struct.Struct(">f")
_DOUBLE_BE = struct.Struct(">d")

# Dispatch tables (fast attribute lookup + avoids long if/elif chain)
_SPECIAL_PARSERS: dict[EDMI_TYPE, Callable[[memoryview], object]] = {
    EDMI_TYPE.BYTE: lambda b: b[0],
    EDMI_TYPE.BOOLEAN: lambda b: b[0],
    EDMI_TYPE.DATE: lambda b: parse_date(b),
    EDMI_TYPE.TIME: lambda b: parse_time(b),
    EDMI_TYPE.DATE_TIME: lambda b: parse_datetime(b),
    EDMI_TYPE.SERIAL_NUMBER: lambda b: parse_serial_number(b),
    EDMI_TYPE.ERROR_STRING: lambda b: parse_error(b),
    EDMI_TYPE.STRING: lambda b: parse_null_terminated_string(b),
    EDMI_TYPE.STRING_LONG: lambda b: parse_null_terminated_string(b),
    EDMI_TYPE.EFA_STRING: lambda b: parse_null_terminated_string(b),
}

_NUMERIC_UNPACKERS: dict[EDMI_TYPE, Callable[[memoryview], object]] = {
    EDMI_TYPE.DOUBLE: lambda b: _DOUBLE_BE.unpack(b)[0],
    EDMI_TYPE.DOUBLE_ENERGY: lambda b: _DOUBLE_BE.unpack(b)[0],
    EDMI_TYPE.FLOAT: lambda b: _FLOAT_BE.unpack(b)[0],
    EDMI_TYPE.FLOAT_ENERGY: lambda b: _FLOAT_BE.unpack(b)[0],
    EDMI_TYPE.POWER_FACTOR: lambda b: _FLOAT_BE.unpack(b)[0],
    EDMI_TYPE.SHORT: lambda b: _I16_BE.unpack(b)[0],
    EDMI_TYPE.HEX_SHORT: lambda b: _U16_BE.unpack(b)[0],
    EDMI_TYPE.LONG: lambda b: _I32_BE.unpack(b)[0],
    EDMI_TYPE.HEX_LONG: lambda b: _U32_BE.unpack(b)[0],
    EDMI_TYPE.REGISTER_NUMBER_HEX_LONG: lambda b: _U32_BE.unpack(b)[0],
    EDMI_TYPE.LONG_LONG: lambda b: _I64_BE.unpack(b)[0],
}


def _parse_value(reg_type: EDMI_TYPE, chunk: memoryview) -> object:
    parser = _SPECIAL_PARSERS.get(reg_type)
    if parser is not None:
        return parser(chunk)

    unpacker = _NUMERIC_UNPACKERS.get(reg_type)
    if unpacker is not None:
        return unpacker(chunk)

    # Default: treat as float, same as your current else-path.
    return _FLOAT_BE.unpack(chunk)[0]


def edmi_parse_read_registers_answer(
    payload: bytes | memoryview,
    regs: Sequence[EDMIRegister],
) -> EDMI_ERROR_CODE:
    mv = payload if isinstance(payload, memoryview) else memoryview(payload)

    if mv.nbytes < 13:
        logger.warning("REQUEST_WRONG_LENGTH#1")
        return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH

    if mv[12] != EDMI_COMMAND_TYPE.READ_REGISTER_EXTENDED:
        return EDMI_ERROR_CODE.REQUEST_RESPONSE_COMMAND_MISMATCH

    miden = int.from_bytes(mv[13:17], "big")
    if miden != EDMI_MULTI_ERR_IDEN:
        return EDMI_ERROR_CODE.REQUEST_RESPONSE_COMMAND_MISMATCH

    # Exclude CRC(2) + ETX(1) from data parsing.
    if mv.nbytes < 3:
        logger.warning("REQUEST_WRONG_LENGTH#2")
        return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
    data_end = mv.nbytes - 3

    idx = 17

    for reg in regs:
        reg.ErrorCode = mv[idx]
        idx += 1

        value_len = reg.ValueLen
        end = idx
        if reg.ErrorCode == EDMI_ERROR_CODE.NONE:
            if reg.Type in (EDMI_TYPE.STRING, EDMI_TYPE.STRING_LONG, EDMI_TYPE.EFA_STRING):
                logger.warning(reg.Name)
                if idx >= data_end:
                    logger.warning("REQUEST_WRONG_LENGTH#3")
                    return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
                scan_len = min(value_len, data_end - idx)
                chunk = mv[idx : idx + scan_len].tobytes()
                nul = chunk.find(b"\x00")
                if nul >= 0:
                    reg.Value = chunk[:nul].decode("ascii", "strict")
                    idx += nul + 1
                elif scan_len < value_len:
                    logger.warning("REQUEST_WRONG_LENGTH#3")
                    return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
                else:
                    reg.Value = chunk.decode("ascii", "strict")
                    idx += value_len
                end = idx
            else:
                if idx + value_len > data_end:
                    logger.warning("REQUEST_WRONG_LENGTH#5")
                    return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
                end = idx + value_len
                reg.Value = _parse_value(reg.Type, mv[idx:end])
                idx = end
        elif reg.ErrorCode == EDMI_ERROR_CODE.REGISTER_NOT_FOUND:
            reg.Value = None
            end = idx
            logger.warning("Register not found: %s", reg.Name)
        else:
            reg.Value = None
            if idx + value_len > data_end:
                logger.warning(
                    "REQUEST_WRONG_LENGTH#6 err=%s addr=%s name=%s idx=%s value_len=%s data_end=%s",
                    int(reg.ErrorCode),
                    int(reg.Address),
                    reg.Name,
                    idx,
                    value_len,
                    data_end,
                )
                # Some meters omit data bytes when an error is returned for a register.
                return EDMI_ERROR_CODE(int(reg.ErrorCode))
            end = idx
        idx = end

        logger.info(
            "REG name=%s addr=0x%04X value=%s err=0x%02X len=%s",
            reg.Name,
            int(reg.Address),
            reg.Value,
            int(reg.ErrorCode),
            int(reg.ValueLen),
        )

    return EDMI_ERROR_CODE.NONE
