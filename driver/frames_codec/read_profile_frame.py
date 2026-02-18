from __future__ import annotations

import struct
import logging
from typing import Sequence
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
import logging

from driver.edmi_enums import (
    EDMI_COMMAND_EXTENSION,
    EDMI_COMMAND_TYPE,
    EDMI_ERROR_CODE,
    EDMI_RESPONSE_CODE,
    EDMI_TYPE,
    EDMI_UNIT_CODE,
)
from driver.frames_codec.generics import edmi_begin_init_packet, edmi_end_init_packet
from driver.interface.edmi_structs import (
    EDMIDateTime,
    EDMIFileChannelInfo,
    EDMIFileField,
    EDMIFileInfo,
    EDMIProfileSpec,
    EDMIReadFile,
    EDMIRegister,
    EDMISearchFile,
    MAX_VALUE_LENGTH,
)


logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
log.propagate = True
_U16_BE = struct.Struct(">H")
_I16_BE = struct.Struct(">h")
_U32_BE = struct.Struct(">I")
_I32_BE = struct.Struct(">i")
_I64_BE = struct.Struct(">q")
_F32_BE = struct.Struct(">f")
_F64_BE = struct.Struct(">d")


def edmi_create_read_profile_info_access_packet(serial: int, survey: int) -> bytes:
    base = edmi_begin_init_packet(
        serial=serial,
        command_type=EDMI_COMMAND_TYPE.FILE_ACCESS,
        command_extension=EDMI_COMMAND_EXTENSION.FILE_INFO,
    )

    # C: WriteInt32((survey << 16) | 0xF008)
    reg_addr = ((int(survey) & 0xFFFF) << 16) | 0xF008

    buf = bytearray(len(base) + 4)
    mv = memoryview(buf)
    mv[: len(base)] = base
    _U32_BE.pack_into(mv, len(base), reg_addr & 0xFFFFFFFF)

    return edmi_end_init_packet(mv)


def edmi_create_search_profile_packet(
    serial: int,
    survey: int,
    start_record: int,
    dt: EDMIDateTime,
    dir_or_result: int,
) -> bytes:
    """
    dt is EDMIDateTime; writes in C order: Day Month Year Hour Minute Second.
    """
    base = edmi_begin_init_packet(
        serial=serial,
        command_type=EDMI_COMMAND_TYPE.FILE_ACCESS,
        command_extension=EDMI_COMMAND_EXTENSION.FILE_SEARCH,
    )

    reg_addr = ((int(survey) & 0xFFFF) << 16) | 0xF008

    # Payload:
    #   u32 reg_addr
    #   i32 start_record
    #   6 bytes datetime
    #   u8 dir
    payload_len = 4 + 4 + 6 + 1
    buf = bytearray(len(base) + payload_len)
    mv = memoryview(buf)

    mv[: len(base)] = base
    i = len(base)

    _U32_BE.pack_into(mv, i, reg_addr & 0xFFFFFFFF); i += 4
    _I32_BE.pack_into(mv, i, int(start_record)); i += 4

    mv[i] = int(dt.Day) & 0xFF; i += 1
    mv[i] = int(dt.Month) & 0xFF; i += 1
    mv[i] = int(dt.Year) & 0xFF; i += 1
    mv[i] = int(dt.Hour) & 0xFF; i += 1
    mv[i] = int(dt.Minute) & 0xFF; i += 1
    mv[i] = int(dt.Second) & 0xFF; i += 1

    mv[i] = int(dir_or_result) & 0xFF; i += 1

    return edmi_end_init_packet(mv)


def edmi_create_read_profile_packet(
    serial: int,
    survey: int,
    start_record: int,
    records_count: int,
    record_offset: int,
    record_size: int,
) -> bytes:
    base = edmi_begin_init_packet(
        serial=serial,
        command_type=EDMI_COMMAND_TYPE.FILE_ACCESS,
        command_extension=EDMI_COMMAND_EXTENSION.FILE_READ,
    )

    reg_addr = ((int(survey) & 0xFFFF) << 16) | 0xF008

    # C payload:
    #   u32 reg_addr
    #   i32 start_record
    #   i16 records_count
    #   i16 record_offset
    #   i16 record_size
    payload_len = 4 + 4 + 2 + 2 + 2
    buf = bytearray(len(base) + payload_len)
    mv = memoryview(buf)

    mv[: len(base)] = base
    i = len(base)

    _U32_BE.pack_into(mv, i, reg_addr & 0xFFFFFFFF); i += 4
    _I32_BE.pack_into(mv, i, int(start_record)); i += 4
    _I16_BE.pack_into(mv, i, int(records_count)); i += 2
    _I16_BE.pack_into(mv, i, int(record_offset)); i += 2
    _I16_BE.pack_into(mv, i, int(record_size)); i += 2

    return edmi_end_init_packet(mv)


def edmi_get_file_info_regs(survey: int) -> list[EDMIRegister]:
    mask = int(survey) << 16
    return [
        EDMIRegister(
            Name="Profile Interval",
            Address=mask | 0xF014,
            Type=EDMI_TYPE.LONG,
            UnitCode=EDMI_UNIT_CODE.SECONDS,
            ErrorCode=None,
            Value=None,
            ValueLen=4,
        ),
        EDMIRegister(
            Name="Profile Channels Count",
            Address=mask | 0xF012,
            Type=EDMI_TYPE.BYTE,
            UnitCode=EDMI_UNIT_CODE.NO_UNIT,
            ErrorCode=None,
            Value=None,
            ValueLen=1,
        ),
    ]


def edmi_set_profile_info(info: EDMIFileInfo, regs: Sequence[EDMIRegister]) -> EDMI_ERROR_CODE:
    if len(regs) < 2:
        return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH

    reg = regs[0]
    if reg.ErrorCode not in (None, 0, EDMI_ERROR_CODE.NONE):
        return EDMI_ERROR_CODE(int(reg.ErrorCode))
    info.Interval = int(reg.Value)

    reg = regs[1]
    if reg.ErrorCode not in (None, 0, EDMI_ERROR_CODE.NONE):
        return EDMI_ERROR_CODE(int(reg.ErrorCode))
    info.ChannelsCount = int(reg.Value) + 1

    return EDMI_ERROR_CODE.NONE


def edmi_get_file_channel_regs(survey: int, channel: int) -> list[EDMIRegister]:
    mask = int(survey) << 16
    return [
        EDMIRegister(
            Name=f"Channel {channel} Type",
            Address=mask | ((0xE2 << 8) | (channel & 0xFF)),
            Type=EDMI_TYPE.BYTE,
            UnitCode=EDMI_UNIT_CODE.NO_UNIT,
            ErrorCode=None,
            Value=None,
            ValueLen=1,
        ),
        EDMIRegister(
            Name=f"Channel {channel} UnitCode",
            Address=mask | ((0xE3 << 8) | (channel & 0xFF)),
            Type=EDMI_TYPE.BYTE,
            UnitCode=EDMI_UNIT_CODE.NO_UNIT,
            ErrorCode=None,
            Value=None,
            ValueLen=1,
        ),
        EDMIRegister(
            Name=f"Channel {channel} ScalingCode",
            Address=mask | ((0xE6 << 8) | (channel & 0xFF)),
            Type=EDMI_TYPE.BYTE,
            UnitCode=EDMI_UNIT_CODE.NO_UNIT,
            ErrorCode=None,
            Value=None,
            ValueLen=1,
        ),
        EDMIRegister(
            Name=f"Channel {channel} ScalingFactor",
            Address=mask | ((0xE8 << 8) | (channel & 0xFF)),
            Type=EDMI_TYPE.FLOAT,
            UnitCode=EDMI_UNIT_CODE.NO_UNIT,
            ErrorCode=None,
            Value=None,
            ValueLen=4,
        ),
        EDMIRegister(
            Name=f"Channel {channel} Name",
            Address=mask | ((0xE4 << 8) | (channel & 0xFF)),
            Type=EDMI_TYPE.STRING,
            UnitCode=EDMI_UNIT_CODE.NO_UNIT,
            ErrorCode=None,
            Value=None,
            ValueLen=MAX_VALUE_LENGTH,
        ),
    ]


def edmi_set_file_channel_info(
    info: EDMIFileChannelInfo,
    regs: Sequence[EDMIRegister],
) -> EDMI_ERROR_CODE:
    if len(regs) < 5:
        return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH

    reg = regs[0]
    if reg.ErrorCode not in (None, 0, EDMI_ERROR_CODE.NONE):
        return EDMI_ERROR_CODE(int(reg.ErrorCode))
    info.Type = int(reg.Value)

    reg = regs[1]
    if reg.ErrorCode not in (None, 0, EDMI_ERROR_CODE.NONE):
        return EDMI_ERROR_CODE(int(reg.ErrorCode))
    info.UnitCode = int(reg.Value)

    reg = regs[2]
    if reg.ErrorCode not in (None, 0, EDMI_ERROR_CODE.NONE):
        return EDMI_ERROR_CODE(int(reg.ErrorCode))
    info.ScalingCode = int(reg.Value)

    reg = regs[3]
    if reg.ErrorCode not in (None, 0, EDMI_ERROR_CODE.NONE):
        return EDMI_ERROR_CODE(int(reg.ErrorCode))
    info.ScalingFactor = float(reg.Value)

    reg = regs[4]
    if reg.ErrorCode not in (None, 0, EDMI_ERROR_CODE.NONE):
        return EDMI_ERROR_CODE(int(reg.ErrorCode))
    info.Name = str(reg.Value)

    return EDMI_ERROR_CODE.NONE


def edmi_parse_read_profile_info_access_payload(
    payload: bytes | memoryview,
    info: EDMIFileInfo,
) -> EDMI_ERROR_CODE:
    mv = payload if isinstance(payload, memoryview) else memoryview(payload)
    idx = 12
    if mv.nbytes <= idx:
        return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH

    result = mv[idx]
    idx += 1
    if result == EDMI_RESPONSE_CODE.CAN:
        if idx >= mv.nbytes:
            return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
        try:
            return EDMI_ERROR_CODE(mv[idx])
        except ValueError:
            return EDMI_ERROR_CODE.REQUEST_RESPONSE_COMMAND_MISMATCH

    if result != EDMI_COMMAND_TYPE.FILE_ACCESS:
        return EDMI_ERROR_CODE.REQUEST_RESPONSE_COMMAND_MISMATCH

    if idx >= mv.nbytes:
        return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
    ext = mv[idx]
    idx += 1
    if ext != EDMI_COMMAND_EXTENSION.FILE_INFO:
        return EDMI_ERROR_CODE.REQUEST_RESPONSE_COMMAND_MISMATCH

    reg_addr, idx, err = _read_u32(mv, idx)
    if err != EDMI_ERROR_CODE.NONE:
        return err
    _ = reg_addr

    start_record, idx, err = _read_i32(mv, idx)
    if err != EDMI_ERROR_CODE.NONE:
        return err
    records_count, idx, err = _read_i32(mv, idx)
    if err != EDMI_ERROR_CODE.NONE:
        return err
    record_size, idx, err = _read_i16(mv, idx)
    if err != EDMI_ERROR_CODE.NONE:
        return err

    if idx >= mv.nbytes:
        return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
    info_type = mv[idx]
    idx += 1

    name, idx, err = _read_cstring(mv, idx, MAX_VALUE_LENGTH)
    if err != EDMI_ERROR_CODE.NONE:
        return err

    info.StartRecord = int(start_record)
    info.RecordsCount = int(records_count)
    info.RecordSize = int(record_size)
    info.Type = int(info_type)
    info.Name = name

    return EDMI_ERROR_CODE.NONE


def edmi_parse_search_profile_payload(
    payload: bytes | memoryview,
    search: EDMISearchFile,
) -> EDMI_ERROR_CODE:
    mv = payload if isinstance(payload, memoryview) else memoryview(payload)
    idx = 12
    if mv.nbytes <= idx:
        return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH

    result = mv[idx]
    idx += 1
    if result == EDMI_RESPONSE_CODE.CAN:
        if idx >= mv.nbytes:
            return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
        try:
            return EDMI_ERROR_CODE(mv[idx])
        except ValueError:
            return EDMI_ERROR_CODE.REQUEST_RESPONSE_COMMAND_MISMATCH

    if result != EDMI_COMMAND_TYPE.FILE_ACCESS:
        return EDMI_ERROR_CODE.REQUEST_RESPONSE_COMMAND_MISMATCH

    if idx >= mv.nbytes:
        return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
    ext = mv[idx]
    idx += 1
    if ext != EDMI_COMMAND_EXTENSION.FILE_SEARCH:
        return EDMI_ERROR_CODE.REQUEST_RESPONSE_COMMAND_MISMATCH

    reg_addr, idx, err = _read_u32(mv, idx)
    if err != EDMI_ERROR_CODE.NONE:
        return err
    _ = reg_addr

    start_record, idx, err = _read_i32(mv, idx)
    if err != EDMI_ERROR_CODE.NONE:
        return err

    dt, idx, err = _read_datetime(mv, idx)
    if err != EDMI_ERROR_CODE.NONE:
        return err

    if idx >= mv.nbytes:
        return EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
    dir_or_result = mv[idx]
    idx += 1

    search.StartRecord = int(start_record)
    search.DateTime = dt
    search.DirOrResult = int(dir_or_result)

    return EDMI_ERROR_CODE.NONE


def edmi_parse_read_profile_payload(
    payload: bytes | memoryview,
    read: EDMIReadFile,
    profile_spec: EDMIProfileSpec,
) -> tuple[list[EDMIFileField], EDMI_ERROR_CODE]:
    print("edmi_parse_read_profile_payload: parsing payload of length", len(payload))
    mv = payload if isinstance(payload, memoryview) else memoryview(payload)

    if mv.nbytes < 3:
        log.info("edmi_parse_read_profile_payload: payload too short: %d bytes", mv.nbytes)
        return [], EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
    else:
        log.info("edmi_parse_read_profile_payload: payload length: %d bytes", mv.nbytes)
    data_end = mv.nbytes - 3  # exclude CRC + ETX
    idx = 12

    if data_end <= idx:
        log.info("edmi_parse_read_profile_payload: no data after header: %d bytes", mv.nbytes)
        return [], EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
    else:
        log.info("edmi_parse_read_profile_payload: data length after header: %d bytes", data_end - idx)

    # ---- Response code ----
    result = mv[idx]
    idx += 1

    if result == EDMI_RESPONSE_CODE.CAN:
        return [], EDMI_ERROR_CODE(mv[idx])

    if result != EDMI_COMMAND_TYPE.FILE_ACCESS:
        return [], EDMI_ERROR_CODE.REQUEST_RESPONSE_COMMAND_MISMATCH

    ext = mv[idx]
    idx += 1

    if ext != EDMI_COMMAND_EXTENSION.FILE_READ:
        return [], EDMI_ERROR_CODE.REQUEST_RESPONSE_COMMAND_MISMATCH

    # ---- Header fields ----
    _, idx, err = _read_u32(mv, idx)
    if err != EDMI_ERROR_CODE.NONE:
        return [], err

    start_record, idx, err = _read_i32(mv, idx)
    if err != EDMI_ERROR_CODE.NONE:
        return [], err

    records_count, idx, err = _read_i16(mv, idx)
    if err != EDMI_ERROR_CODE.NONE:
        return [], err

    record_offset, idx, err = _read_i16(mv, idx)
    if err != EDMI_ERROR_CODE.NONE:
        return [], err

    record_size, idx, err = _read_i16(mv, idx)
    if err != EDMI_ERROR_CODE.NONE:
        return [], err

    read.StartRecord = int(start_record)
    read.RecordsCount = int(records_count)
    read.RecordOffset = int(record_offset)
    read.RecordSize = int(record_size)

    if records_count <= 0:
        pass # No records to parse
    channels_per_record = profile_spec.ChannelsCount
    log.info("Parsing %d records of size %d with %d channels", read.RecordsCount, read.RecordSize, channels_per_record)
    
    fields: list[EDMIFileField] = []
    for record in range(read.RecordsCount):

        record_start = idx
        record_end = record_start + record_size

        if record_end > data_end:
            break

        record_mv = mv[record_start:record_end]
        r_idx = 0


        # 3️⃣ Read channel values
        for ch in range(profile_spec.ChannelsCount):
            # Calculate remaining space logic to handle variable/compressed fields
            tail_channels = profile_spec.ChannelsInfo[ch + 1:]
            min_tail = 0
            for tc in tail_channels:
                l = _expected_value_len(tc.Type)
                if l is not None:
                    min_tail += l
            
            # Constraints
            current_available = len(record_mv) - r_idx
            max_len = current_available - min_tail

            value, r_idx, err = _read_value(record_mv, r_idx, profile_spec.ChannelsInfo[ch].Type, max_len=max_len)
            if err != EDMI_ERROR_CODE.NONE:
                log.error(
                    "Parsing failed at record %d channel %d (Type=%s). idx=%d record_end=%d mv_len=%d err=%s",
                    record, ch, profile_spec.ChannelsInfo[ch].Type, idx, record_end, len(record_mv), err
                )
                return [], err
            fields.append(EDMIFileField(Value=value))

        idx = record_end

    return fields, EDMI_ERROR_CODE.NONE



def _expected_value_len(value_type: int) -> int | None:
    try:
        vtype = EDMI_TYPE(value_type)
    except ValueError:
        return None

    if vtype in (EDMI_TYPE.BYTE, EDMI_TYPE.BOOLEAN):
        return 1
    if vtype in (EDMI_TYPE.SHORT, EDMI_TYPE.HEX_SHORT):
        return 2
    if vtype in (EDMI_TYPE.LONG, EDMI_TYPE.HEX_LONG, EDMI_TYPE.REGISTER_NUMBER_HEX_LONG):
        return 4
    if vtype == EDMI_TYPE.LONG_LONG:
        return 8
    if vtype in (EDMI_TYPE.FLOAT, EDMI_TYPE.FLOAT_ENERGY, EDMI_TYPE.POWER_FACTOR):
        return 4
    if vtype in (EDMI_TYPE.DOUBLE, EDMI_TYPE.DOUBLE_ENERGY):
        return 8
    if vtype == EDMI_TYPE.DATE:
        return 3
    if vtype == EDMI_TYPE.TIME:
        return 3
    if vtype == EDMI_TYPE.DATE_TIME:
        return 6
    if vtype == EDMI_TYPE.ERROR_STRING:
        return 16

    return None


def _read_u32(mv: memoryview, idx: int) -> tuple[int, int, EDMI_ERROR_CODE]:
    if idx + 4 > mv.nbytes:
        log.info("edmi_parse_read_profile_payload: _read_u32: payload too short: %d bytes", mv.nbytes)
        return 0, idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
    return _U32_BE.unpack_from(mv, idx)[0], idx + 4, EDMI_ERROR_CODE.NONE


def _read_i32(mv: memoryview, idx: int) -> tuple[int, int, EDMI_ERROR_CODE]:
    if idx + 4 > mv.nbytes:
        log.info("edmi_parse_read_profile_payload: _read_i32: payload too short: %d bytes", mv.nbytes)
        return 0, idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
    return _I32_BE.unpack_from(mv, idx)[0], idx + 4, EDMI_ERROR_CODE.NONE


def _read_i16(mv: memoryview, idx: int) -> tuple[int, int, EDMI_ERROR_CODE]:
    if idx + 2 > mv.nbytes:
        log.info("edmi_parse_read_profile_payload: _read_i16: payload too short: %d bytes", mv.nbytes)
        return 0, idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
    return _I16_BE.unpack_from(mv, idx)[0], idx + 2, EDMI_ERROR_CODE.NONE


def _read_datetime(mv: memoryview, idx: int, max_len: int = 6) -> tuple[EDMIDateTime, int, EDMI_ERROR_CODE]:
    # Check for compressed 4-byte timestamp (Gen 5 / compacted profiles)
    if max_len < 6 and max_len >= 4:
         # Try 4-byte read
         if idx + 4 <= mv.nbytes:
             secs, next_idx, err = _read_u32(mv, idx)
             if err == EDMI_ERROR_CODE.NONE:
                 # Base date: 1996-01-01
                 base = datetime(1996, 1, 1)
                 try:
                    dt_obj = base + timedelta(seconds=secs)
                    dt = EDMIDateTime(
                        Year=dt_obj.year - 2000 if dt_obj.year >= 2000 else dt_obj.year - 1900,
                        Month=dt_obj.month,
                        Day=dt_obj.day,
                        Hour=dt_obj.hour,
                        Minute=dt_obj.minute,
                        Second=dt_obj.second,
                        IsNull=False,
                    )
                    log.debug("Parsed compressed datetime: %s from %s", dt, secs)
                    return dt, next_idx, EDMI_ERROR_CODE.NONE
                 except Exception:
                     pass # Fallback to error

    if idx + 6 > mv.nbytes:
        log.info("edmi_parse_read_profile_payload: _read_datetime: payload too short: %d bytes", mv.nbytes)
        return EDMIDateTime(0, 0, 0, 0, 0, 0, True), idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
    dt = EDMIDateTime(
        Year=mv[idx + 2],
        Month=mv[idx + 1],
        Day=mv[idx + 0],
        Hour=mv[idx + 3],
        Minute=mv[idx + 4],
        Second=mv[idx + 5],
        IsNull=False,
    )
    return dt, idx + 6, EDMI_ERROR_CODE.NONE


def _read_cstring(mv: memoryview, idx: int, max_len: int) -> tuple[str, int, EDMI_ERROR_CODE]:
    remaining = mv.nbytes - idx
    if remaining <= 0:
        return "", idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH

    scan_len = min(max_len, remaining)
    chunk = mv[idx : idx + scan_len].tobytes()
    pos = chunk.find(b"\x00")
    if pos >= 0:
        return chunk[:pos].decode("ascii", "strict"), idx + pos + 1, EDMI_ERROR_CODE.NONE

    if remaining < max_len:
        return "", idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH

    return chunk.decode("ascii", "strict"), idx + max_len, EDMI_ERROR_CODE.NONE


def _read_fixed_string(
    mv: memoryview, idx: int, size: int
) -> tuple[str, int, EDMI_ERROR_CODE]:
    if idx + size > mv.nbytes:
        return "", idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
    raw = mv[idx : idx + size].tobytes()
    return raw.decode("ascii", "strict"), idx + size, EDMI_ERROR_CODE.NONE


def _read_value(
    mv: memoryview,
    idx: int,
    value_type: int,
    max_len: int | None = None,
) -> tuple[object, int, EDMI_ERROR_CODE]:
    try:
        vtype = EDMI_TYPE(value_type)
    except ValueError:
        return None, idx, EDMI_ERROR_CODE.UNIMPLEMENTED_DATA_TYPE
    if vtype in (EDMI_TYPE.BYTE, EDMI_TYPE.BOOLEAN):
        if idx + 1 > mv.nbytes:
            return None, idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
        return mv[idx], idx + 1, EDMI_ERROR_CODE.NONE

    if vtype in (EDMI_TYPE.STRING, EDMI_TYPE.STRING_LONG, EDMI_TYPE.EFA_STRING):
        return _read_cstring(mv, idx, MAX_VALUE_LENGTH)

    if vtype == EDMI_TYPE.ERROR_STRING:
        return _read_fixed_string(mv, idx, 16)

    if vtype == EDMI_TYPE.SHORT:
        if idx + 2 > mv.nbytes:
            return None, idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
        return _I16_BE.unpack_from(mv, idx)[0], idx + 2, EDMI_ERROR_CODE.NONE

    if vtype == EDMI_TYPE.HEX_SHORT:
        if idx + 2 > mv.nbytes:
            return None, idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
        return _U16_BE.unpack_from(mv, idx)[0], idx + 2, EDMI_ERROR_CODE.NONE

    if vtype == EDMI_TYPE.LONG:
        if idx + 4 > mv.nbytes:
            return None, idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
        return _I32_BE.unpack_from(mv, idx)[0], idx + 4, EDMI_ERROR_CODE.NONE

    if vtype in (EDMI_TYPE.HEX_LONG, EDMI_TYPE.REGISTER_NUMBER_HEX_LONG):
        if idx + 4 > mv.nbytes:
            return None, idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
        return _U32_BE.unpack_from(mv, idx)[0], idx + 4, EDMI_ERROR_CODE.NONE

    if vtype == EDMI_TYPE.LONG_LONG:
        if idx + 8 > mv.nbytes:
            return None, idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
        return _I64_BE.unpack_from(mv, idx)[0], idx + 8, EDMI_ERROR_CODE.NONE

    if vtype in (EDMI_TYPE.FLOAT, EDMI_TYPE.POWER_FACTOR):
        if idx + 4 > mv.nbytes:
            return None, idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
        return _F32_BE.unpack_from(mv, idx)[0], idx + 4, EDMI_ERROR_CODE.NONE

    if vtype == EDMI_TYPE.FLOAT_ENERGY:
        if idx + 4 > mv.nbytes:
            return None, idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
        return _I32_BE.unpack_from(mv, idx)[0], idx + 4, EDMI_ERROR_CODE.NONE

    if vtype == EDMI_TYPE.DOUBLE:
        if idx + 8 > mv.nbytes:
            return None, idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
        return _F64_BE.unpack_from(mv, idx)[0], idx + 8, EDMI_ERROR_CODE.NONE

    if vtype == EDMI_TYPE.DOUBLE_ENERGY:
        if idx + 8 > mv.nbytes:
            return None, idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
        return _I64_BE.unpack_from(mv, idx)[0], idx + 8, EDMI_ERROR_CODE.NONE

    if vtype == EDMI_TYPE.DATE:
        if idx + 3 > mv.nbytes:
            return None, idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
        dt = EDMIDateTime(
            Year=mv[idx + 2],
            Month=mv[idx + 1],
            Day=mv[idx + 0],
            Hour=0,
            Minute=0,
            Second=0,
            IsNull=False,
        )
        return dt, idx + 3, EDMI_ERROR_CODE.NONE

    if vtype == EDMI_TYPE.TIME:
        if idx + 3 > mv.nbytes:
            return None, idx, EDMI_ERROR_CODE.REQUEST_WRONG_LENGTH
        dt = EDMIDateTime(
            Year=0,
            Month=0,
            Day=0,
            Hour=mv[idx + 0],
            Minute=mv[idx + 1],
            Second=mv[idx + 2],
            IsNull=False,
        )
        return dt, idx + 3, EDMI_ERROR_CODE.NONE

    if vtype == EDMI_TYPE.DATE_TIME:
        # Pass max_len down if provided, default to 6
        limit = 6
        if max_len is not None:
            limit = max_len
        return _read_datetime(mv, idx, max_len=limit)

    return None, idx, EDMI_ERROR_CODE.UNIMPLEMENTED_DATA_TYPE
