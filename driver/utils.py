
from __future__ import annotations

from typing import Union, List, Dict
from driver.interface.edmi_structs import EDMIRegister, EDMISurvey

from datetime import datetime, timedelta
from typing import Any

from driver.edmi_enums import EDMI_TYPE
from driver.interface.edmi_structs import EDMIDateTime, EDMIFileField, EDMIProfileSpec


BytesLike = Union[bytes, bytearray, memoryview]


def combine_packets(*packets: BytesLike) -> bytes:
    """
    Combine multiple packets into one contiguous bytes stream efficiently.

    - Single allocation for the final output.
    - Copies each packet exactly once.
    - Accepts bytes/bytearray/memoryview.
    """
    if not packets:
        return b""

    # Convert to memoryviews (zero-copy views) and compute total length.
    mvs: list[memoryview] = []
    total = 0
    for p in packets:
        mv = p if isinstance(p, memoryview) else memoryview(p)
        mvs.append(mv)
        total += mv.nbytes

    out = bytearray(total)
    out_mv = memoryview(out)

    i = 0
    for mv in mvs:
        n = mv.nbytes
        out_mv[i : i + n] = mv
        i += n

    return bytes(out)

def bytes_to_hex(data: bytes) -> str:
    return " ".join(f"{b:02x}" for b in data)

def as_bytes(x: Union[str, BytesLike], encoding: str = "ascii") -> memoryview:
    if isinstance(x, memoryview):
        return x
    if isinstance(x, (bytes, bytearray)):
        return memoryview(x)
    if isinstance(x, str):
        return memoryview(x.encode(encoding))
    raise TypeError(f"expected str or bytes-like, received {type(x).__name__}")


def _edmi_datetime_to_datetime(dt: EDMIDateTime | None) -> datetime | None:
    if dt is None or dt.IsNull:
        return None
    year = dt.Year
    if year < 100:
        year += 2000
    return datetime(year, dt.Month, dt.Day, dt.Hour, dt.Minute, dt.Second)


def _format_edmi_datetime(dt: EDMIDateTime | None) -> str | None:
    if dt is None or dt.IsNull:
        return None
    if dt.Year == 0 and dt.Month == 0 and dt.Day == 0:
        return f"{dt.Hour:02d}:{dt.Minute:02d}:{dt.Second:02d}"
    py_dt = _edmi_datetime_to_datetime(dt)
    if py_dt is None:
        return None
    return py_dt.isoformat(sep=" ")


def _format_edmi_date(dt: EDMIDateTime | None) -> str | None:
    if dt is None or dt.IsNull:
        return None
    py_dt = _edmi_datetime_to_datetime(dt)
    if py_dt is None:
        return None
    return py_dt.date().isoformat()


def _format_edmi_time(dt: EDMIDateTime | None) -> str | None:
    if dt is None or dt.IsNull:
        return None
    return f"{dt.Hour:02d}:{dt.Minute:02d}:{dt.Second:02d}"


def _scaled_value(value: Any, factor: float | None) -> Any:
    if factor is None:
        return value
    try:
        return value * factor
    except TypeError:
        return value


def _format_channel_value(raw: Any, vtype: EDMI_TYPE, scaling_factor: float | None) -> Any:
    if raw is None:
        return None

    if vtype == EDMI_TYPE.BOOLEAN:
        return bool(raw)
    if vtype == EDMI_TYPE.BYTE:
        return int(raw)
    if vtype in (EDMI_TYPE.STRING, EDMI_TYPE.STRING_LONG, EDMI_TYPE.EFA_STRING, EDMI_TYPE.ERROR_STRING):
        return raw
    if vtype == EDMI_TYPE.DATE_TIME:
        return _format_edmi_datetime(raw)
    if vtype == EDMI_TYPE.DATE:
        return _format_edmi_date(raw)
    if vtype == EDMI_TYPE.TIME:
        return _format_edmi_time(raw)
    if vtype == EDMI_TYPE.FLOAT_ENERGY:
        value_u32 = int(raw) & 0xFFFFFFFF
        return _scaled_value(value_u32, scaling_factor)
    if vtype == EDMI_TYPE.DOUBLE_ENERGY:
        if isinstance(raw, int):
            value_u64 = raw & 0xFFFFFFFFFFFFFFFF
            return _scaled_value(value_u64, scaling_factor)
        return _scaled_value(raw, scaling_factor)
    if vtype in (EDMI_TYPE.FLOAT, EDMI_TYPE.POWER_FACTOR, EDMI_TYPE.DOUBLE):
        return _scaled_value(raw, scaling_factor)
    if vtype in (
        EDMI_TYPE.SHORT,
        EDMI_TYPE.HEX_SHORT,
        EDMI_TYPE.LONG,
        EDMI_TYPE.HEX_LONG,
        EDMI_TYPE.REGISTER_NUMBER_HEX_LONG,
        EDMI_TYPE.LONG_LONG,
    ):
        return _scaled_value(int(raw), scaling_factor)

    return raw


def format_parsed_profile_data(
    profile_spec: EDMIProfileSpec,
    fields: list[EDMIFileField],
) -> list[dict[str, Any]]:
    channels_count = profile_spec.ChannelsCount
    if channels_count <= 0:
        return []

    records_count = profile_spec.RecordsCount or (len(fields) // channels_count)
    start_dt = _edmi_datetime_to_datetime(profile_spec.FromDateTime)
    interval_sec = profile_spec.Interval
    base_record = getattr(profile_spec, "StartRecord", 0)

    records: list[dict[str, Any]] = []
    idx = 0
    for record_idx in range(records_count):
        item: dict[str, Any] = {}
        item["record_number"] = base_record + record_idx
        if start_dt is None:
            item["timestamp"] = None
        elif interval_sec > 0:
            item["timestamp"] = (start_dt + timedelta(seconds=interval_sec * record_idx)).isoformat(sep=" ")
        else:
            item["timestamp"] = start_dt.isoformat(sep=" ")

        for ch in range(channels_count):
            field = fields[idx]
            idx += 1
            ch_info = profile_spec.ChannelsInfo[ch]
            try:
                vtype = EDMI_TYPE(ch_info.Type)
            except ValueError:
                vtype = None

            raw = field.Value
            scaling = getattr(ch_info, "ScalingFactor", None)
            if profile_spec.Survey == EDMISurvey.LS03 and scaling is not None:
                scaling *= 0.001344
            if vtype is None:
                value = raw
            else:
                value = _format_channel_value(raw, vtype, scaling)

            item[ch_info.Name] = value

        records.append(item)

    return records


def edmi_read_profile_formatter(
    profile_spec: EDMIProfileSpec,
    fields: list[EDMIFileField],
) -> list[dict[str, Any]]:
    return format_parsed_profile_data(profile_spec, fields)
