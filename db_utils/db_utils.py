
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Callable, Mapping

from driver.interface.edmi_structs import EDMIRegister
from driver.edmi_enums import EDMI_ERROR_CODE, EDMI_REGISTER
import hashlib
from sqlalchemy import select
from sqlalchemy.orm import Session
from model.models import User


def ensure_default_admin(engine) -> None:
    """
    Creates a default admin user if none exists.
    Safe to run multiple times.
    """
    with Session(engine) as session:
        exists = session.execute(
            select(User).where(User.name == "admin")
        ).scalar_one_or_none()

        if exists:
            return

        admin = User(
            name="admin",
            password_hash=hash_password("admin"),
        )

        session.add(admin)
        session.commit()


def hash_password(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()



# -----------------------------
# Value normalization (EDMI -> Python types for SQLAlchemy)
# -----------------------------

def _to_date(v: object) -> date | None:
    # Your parser returns (day, month, year) where year is 0..99.
    if v is None:
        return None
    if not isinstance(v, tuple) or len(v) != 3:
        return None
    d, m, y = v
    year = 2000 + int(y) if int(y) < 70 else 1900 + int(y)
    return date(year, int(m), int(d))


def _to_time(v: object) -> time | None:
    if v is None:
        return None
    if not isinstance(v, tuple) or len(v) != 3:
        return None
    hh, mm, ss = v
    return time(int(hh), int(mm), int(ss))


def _to_datetime_local(v: object) -> datetime | None:
    # Your parser returns (day, month, year, hour, minute, second) with year 0..99.
    if v is None:
        return None
    if not isinstance(v, tuple) or len(v) != 6:
        return None
    d, m, y, hh, mm, ss = v
    year = 2000 + int(y) if int(y) < 70 else 1900 + int(y)
    return datetime(year, int(m), int(d), int(hh), int(mm), int(ss))


def _as_float(v: object) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _as_str(v: object) -> str | None:
    if v is None:
        return None
    return str(v)


# -----------------------------
# Address -> (column_name, converter)
# -----------------------------

Converter = Callable[[object], object]

@dataclass(frozen=True)
class ColumnSpec:
    column: str
    conv: Converter


_REGISTER_TO_COLUMN: dict[int, ColumnSpec] = {
    # Multipliers / Divisors
    int(EDMI_REGISTER.CURRENT_MULTIPLIER): ColumnSpec("current_multiplier", _as_float),
    int(EDMI_REGISTER.VOLTAGE_MULTIPLIER): ColumnSpec("voltage_multiplier", _as_float),
    int(EDMI_REGISTER.CURRENT_DIVISOR): ColumnSpec("current_divisor", _as_float),
    int(EDMI_REGISTER.VOLTAGE_DIVISOR): ColumnSpec("voltage_divisor", _as_float),

    # Voltages
    int(EDMI_REGISTER.PHASE_A_VOLTAGE): ColumnSpec("phase_a_voltage", _as_float),
    int(EDMI_REGISTER.PHASE_B_VOLTAGE): ColumnSpec("phase_b_voltage", _as_float),
    int(EDMI_REGISTER.PHASE_C_VOLTAGE): ColumnSpec("phase_c_voltage", _as_float),

    # Currents
    int(EDMI_REGISTER.PHASE_A_CURRENT): ColumnSpec("phase_a_current", _as_float),
    int(EDMI_REGISTER.PHASE_B_CURRENT): ColumnSpec("phase_b_current", _as_float),
    int(EDMI_REGISTER.PHASE_C_CURRENT): ColumnSpec("phase_c_current", _as_float),

    # Angles
    int(EDMI_REGISTER.PHASE_A_ANGLE): ColumnSpec("phase_a_angle", _as_float),
    int(EDMI_REGISTER.PHASE_B_ANGLE): ColumnSpec("phase_b_angle", _as_float),
    int(EDMI_REGISTER.PHASE_C_ANGLE): ColumnSpec("phase_c_angle", _as_float),
    int(EDMI_REGISTER.VTA_VTB_ANGLE): ColumnSpec("vta_vtb_angle", _as_float),
    int(EDMI_REGISTER.VTA_VTC_ANGLE): ColumnSpec("vta_vtc_angle", _as_float),

    # Watts
    int(EDMI_REGISTER.PHASE_A_WATTS): ColumnSpec("phase_a_watts", _as_float),
    int(EDMI_REGISTER.PHASE_B_WATTS): ColumnSpec("phase_b_watts", _as_float),
    int(EDMI_REGISTER.PHASE_C_WATTS): ColumnSpec("phase_c_watts", _as_float),

    # Vars
    int(EDMI_REGISTER.PHASE_A_VARS): ColumnSpec("phase_a_vars", _as_float),
    int(EDMI_REGISTER.PHASE_B_VARS): ColumnSpec("phase_b_vars", _as_float),
    int(EDMI_REGISTER.PHASE_C_VARS): ColumnSpec("phase_c_vars", _as_float),

    # VA
    int(EDMI_REGISTER.PHASE_A_VA): ColumnSpec("phase_a_va", _as_float),
    int(EDMI_REGISTER.PHASE_B_VA): ColumnSpec("phase_b_va", _as_float),
    int(EDMI_REGISTER.PHASE_C_VA): ColumnSpec("phase_c_va", _as_float),

    # Power / Frequency
    int(EDMI_REGISTER.POWER_FACTOR): ColumnSpec("power_factor", _as_float),
    int(EDMI_REGISTER.FREQUENCY): ColumnSpec("frequency", _as_float),

    # Energy Import (double -> store as float)
    int(EDMI_REGISTER.RATE_1_IMPORT_KWH): ColumnSpec("rate_1_import_kwh", _as_float),
    int(EDMI_REGISTER.RATE_2_IMPORT_KWH): ColumnSpec("rate_2_import_kwh", _as_float),
    int(EDMI_REGISTER.RATE_3_IMPORT_KWH): ColumnSpec("rate_3_import_kwh", _as_float),
    int(EDMI_REGISTER.TOTAL_IMPORT_KWH): ColumnSpec("total_import_kwh", _as_float),
    int(EDMI_REGISTER.TOTAL_IMPORT_KVAR): ColumnSpec("total_import_kvar", _as_float),

    # Energy Export
    int(EDMI_REGISTER.RATE_1_EXPORT_KWH): ColumnSpec("rate_1_export_kwh", _as_float),
    int(EDMI_REGISTER.RATE_2_EXPORT_KWH): ColumnSpec("rate_2_export_kwh", _as_float),
    int(EDMI_REGISTER.RATE_3_EXPORT_KWH): ColumnSpec("rate_3_export_kwh", _as_float),
    int(EDMI_REGISTER.TOTAL_EXPORT_KWH): ColumnSpec("total_export_kwh", _as_float),
    int(EDMI_REGISTER.TOTAL_EXPORT_KVAR): ColumnSpec("total_export_kvar", _as_float),

    # THD
    int(EDMI_REGISTER.THD_VOLTAGE_A): ColumnSpec("thd_voltage_a", _as_float),
    int(EDMI_REGISTER.THD_VOLTAGE_B): ColumnSpec("thd_voltage_b", _as_float),
    int(EDMI_REGISTER.THD_VOLTAGE_C): ColumnSpec("thd_voltage_c", _as_float),
    int(EDMI_REGISTER.THD_CURRENT_A): ColumnSpec("thd_current_a", _as_float),
    int(EDMI_REGISTER.THD_CURRENT_B): ColumnSpec("thd_current_b", _as_float),
    int(EDMI_REGISTER.THD_CURRENT_C): ColumnSpec("thd_current_c", _as_float),

    # Totals
    int(EDMI_REGISTER.P_TOTAL): ColumnSpec("p_total", _as_float),
    int(EDMI_REGISTER.Q_TOTAL): ColumnSpec("q_total", _as_float),
    int(EDMI_REGISTER.S_TOTAL): ColumnSpec("s_total", _as_float),

    # Ratios
    int(EDMI_REGISTER.CT_RATIO_PRIMARY): ColumnSpec("ct_ratio_primary", _as_float),
    int(EDMI_REGISTER.CT_RATIO_SECONDARY): ColumnSpec("ct_ratio_secondary", _as_float),
    int(EDMI_REGISTER.VT_RATIO_PRIMARY): ColumnSpec("vt_ratio_primary", _as_float),
    int(EDMI_REGISTER.VT_RATIO_SECONDARY): ColumnSpec("vt_ratio_secondary", _as_float),

    # Diagnostics / Demand
    int(EDMI_REGISTER.ERROR_CODE): ColumnSpec("error_code", _as_str),
    int(EDMI_REGISTER.MAX_DEMAND_KWH_IMPORT): ColumnSpec("max_demand_kwh_import", _as_float),
    int(EDMI_REGISTER.MAX_DEMAND_KWH_EXPORT): ColumnSpec("max_demand_kwh_export", _as_float),

    # Meter Information
    int(EDMI_REGISTER.METER_SERIAL_NUMBER): ColumnSpec("meter_serial_number", _as_str),
    int(EDMI_REGISTER.CURRENT_DATE): ColumnSpec("current_date", _to_date),
    int(EDMI_REGISTER.CURRENT_TIME): ColumnSpec("current_time", _to_time),
    int(EDMI_REGISTER.DATE_TIME): ColumnSpec("meter_date_time", _to_datetime_local),
}


# -----------------------------
# Public API: registers -> dict[column, value]
# -----------------------------

def map_registers_to_reading_columns(regs: list[EDMIRegister]) -> dict[str, Any]:
    """
    Converts EDMI registers into a dict of ReadingValue column values.

    Rules:
      - Only maps known register addresses.
      - If reg.ErrorCode != NONE -> sets mapped column to None (keeps snapshot alignment)
      - Converts DATE/TIME/DATE_TIME tuples into Python date/time/datetime.
      - Converts numeric values to float for Float columns; strings for text columns.
    """
    out: dict[str, Any] = {}

    for reg in regs:
        spec = _REGISTER_TO_COLUMN.get(int(reg.Address))
        if spec is None:
            continue

        err = reg.ErrorCode
        err_is_none = (err == EDMI_ERROR_CODE.NONE) or (err == 0)  # supports int or enum

        if not err_is_none:
            out[spec.column] = None
            continue

        out[spec.column] = spec.conv(reg.Value)

    return out
