from datetime import datetime
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import (
    CheckConstraint, Column, Integer, BigInteger,Float, String, DateTime, Boolean,
    ForeignKey, UniqueConstraint, Date, Time, Index, Text, 
)
import uuid
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import declarative_base, relationship
from app.db import Base

F32 = Float(precision=24)
F64 = Float(precision=53)

class MeterReading(Base):
    __tablename__ = "profile_reading_demo"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    meter_id = Column(Integer, ForeignKey("meters.id", ondelete="CASCADE"), nullable=False)
    meter = relationship("Meter", back_populates="meter_readings")

    # Timestamp of the profile record (from LS03 "time_stamp")
    time_stamp = Column(DateTime(timezone=False), nullable=False)

    # LS03 "Record Status" (0.0 means valid interval record)
    record_status = Column(F64, nullable=True)

    # LS03 cumulative totals (use same meaning as your LS03 keys)
    total_energy_tot_imp_wh = Column(F64, nullable=True)  # "Total Energy Tot IMP Wh @"
    total_energy_tot_exp_wh = Column(F64, nullable=True)  # "Total Energy Tot EXP Wh @"
    total_energy_tot_imp_va = Column(F64, nullable=True)  # "Total Energy Tot IMP va @"
    total_energy_tot_exp_va = Column(F64, nullable=True)  # "Total Energy Tot EXP va @"

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("meter_id", "time_stamp", name="uq_meter_profile_meter_time_demo"),
        Index("ix_meter_profile_meter_time_demo", "meter_id", "time_stamp"),
        Index("ix_meter_profile_time_demo", "time_stamp"),
    )

class IntervalState(Base):
    __tablename__ = "interval_state"

    ts = Column(DateTime, primary_key=True)

    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)

    # keep these booleans
    self_available = Column(Boolean, nullable=False)
    grid_available = Column(Boolean, nullable=False)
    interconnect_available = Column(Boolean, nullable=False)

    # availability booleans for “any present”
    bess_available = Column(Boolean, nullable=False)
    rfs_available = Column(Boolean, nullable=False)

    # NEW: missing counts (0..4)
    bess_missing_count = Column(Integer, nullable=False, default=0)
    rfs_missing_count = Column(Integer, nullable=False, default=0)

    scenario_code = Column(String, nullable=False)



class CalculationPeriod(Base):
    __tablename__ = "calculation_period"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)

    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)

    scenario_code = Column(String, nullable=False)
    formula_code = Column(String, nullable=False)

    interval_count = Column(Integer, nullable=False)


class MonthlyEnergySummary(Base):
    __tablename__ = "monthly_energy_summary"

    id = Column(Integer, primary_key=True)

    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)

    bess_to_lmv_energy_kwh = Column(Float, default=0.0)
    rfs_to_lmv_energy_kwh = Column(Float, default=0.0)
    total_energy_to_lmv_kwh = Column(Float, default=0.0)
    k_factor = Column(Float, default=0.0)
    start_date_time = Column(DateTime, nullable=True)
    end_date_time = Column(DateTime, nullable=True)

    # quality_status = Column(String, nullable=False)
    number_of_inqualified_intervals = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_month"),
    )


class MonthlyCalculationBreakdown(Base):
    __tablename__ = "monthly_calculation_breakdown"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    monthly_summary_id = Column(
        Integer, ForeignKey("monthly_energy_summary.id"), nullable=False
    )

    # ---------------- PERIOD INFO ----------------
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    interval_count = Column(Integer, nullable=False)

    # ---------------- DECISION ----------------
    scenario_code = Column(String, nullable=False)
    formula_code = Column(String, nullable=False)

    # ---------------- RAW ENERGY (THIS PERIOD) ----------------
    bess_energy_kwh = Column(Float, default=0.0)
    rts_energy_kwh = Column(Float, default=0.0)
    self_use_energy_kwh = Column(Float, default=0.0)
    grid_energy_kwh = Column(Float, default=0.0)
    interconnect_energy_kwh = Column(Float, default=0.0)

    # ---------------- K USED ----------------
    k_factor = Column(Float)

    # ---------------- SETTLED RESULT ----------------
    rts_to_lmv_kwh = Column(Float, default=0.0)
    bess_to_lmv_kwh = Column(Float, default=0.0)

class MeterStatusSummary(Base):
    __tablename__ = "meter_status_summary"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meter_id = Column(Integer, nullable=False)

    fault_start_ts = Column(DateTime, nullable=False)
    fault_end_ts = Column(DateTime, nullable=True)

    is_open = Column(Boolean, nullable=False, default=True)

    source_period_id = Column(UUID(as_uuid=True), nullable=False)

class ScenarioWindow(Base):
    __tablename__ = "scenario_window"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    scenario_code = Column(String, nullable=False)

    window_start_ts = Column(DateTime, nullable=False)
    window_end_ts = Column(DateTime, nullable=True)  


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=True, unique=True, index=True)
    full_name = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="viewer")
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_login = Column(DateTime(timezone=True), nullable=True)
    permissions = Column(Text, nullable=True)
    password_hash = Column(String(255), nullable=False)

    meters = relationship(
        "Meter",
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class EnergySite(Base):
    __tablename__ = "energy_sites"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    type = Column(String(50), nullable=False)

    meters = relationship(
        "Meter",
        back_populates="site",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class EnergySource(Base):
    __tablename__ = "energy_sources"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    cost_per_kwh = Column(Float, nullable=False)

    meters = relationship(
        "Meter",
        back_populates="source",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

class EnergyRole(Base):
    __tablename__ = "energy_roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)

    meters = relationship(
        "Meter",
        back_populates="role",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

class Meter(Base):
    __tablename__ = "meters"

    id = Column(Integer, primary_key=True)
    serial_number = Column(Integer, nullable=False, unique=True)
    role_id = Column(Integer, ForeignKey("energy_roles.id", ondelete="SET NULL"), nullable=True)  # SOURCE / SELF_USE / GRID_POINT / INTERCONNECT
    source_id = Column(Integer, ForeignKey("energy_sources.id", ondelete="SET NULL"), nullable=True)  # 1=BESS, 2=RTS
    site_id = Column(Integer, ForeignKey("energy_sites.id", ondelete="SET NULL"), nullable=True)
    username = Column(String(100), nullable=False)
    password = Column(String(100), nullable=False)
    meter_name = Column(String(100), nullable=True)
    outstation = Column(Integer, nullable=True)
    type = Column(String(20), nullable=False)
    model = Column(String(20), nullable=False)
    survey_type = Column(ARRAY(String), nullable=True, default=list)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    owner = relationship("User", back_populates="meters")
    site = relationship("EnergySite", back_populates="meters")
    role = relationship("EnergyRole", back_populates="meters")
    source = relationship("EnergySource", back_populates="meters")

    reading_values = relationship(
        "ReadingValue",
        back_populates="meter",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    meter_readings = relationship(
        "MeterReading",
        back_populates="meter",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    profile_reading_values = relationship(
    "ProfileReadingValue",
    back_populates="meter",
    cascade="all, delete-orphan",
    passive_deletes=True,
)


class ReadingValue(Base):
    """
    Wide table: one row per (meter_id, time_stamp_utc) snapshot.
    Primary key is UUID.
    """
    __tablename__ = "reading_values"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    meter_id = Column(Integer, ForeignKey("meters.id", ondelete="CASCADE"), nullable=False)
    meter = relationship("Meter", back_populates="reading_values")
    time_stamp_utc = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # -----------------------------
    # Multipliers / Divisors (FLOAT, 4 bytes)
    # -----------------------------
    current_multiplier = Column(F32)
    voltage_multiplier = Column(F32)
    current_divisor = Column(F32)
    voltage_divisor = Column(F32)

    # -----------------------------
    # 3 Phase Voltages (FLOAT, 4 bytes)
    # -----------------------------
    phase_a_voltage = Column(F32)
    phase_b_voltage = Column(F32)
    phase_c_voltage = Column(F32)

    # -----------------------------
    # 3 Phase Currents (FLOAT, 4 bytes)
    # -----------------------------
    phase_a_current = Column(F32)
    phase_b_current = Column(F32)
    phase_c_current = Column(F32)

    # -----------------------------
    # 3 Phase Angles (FLOAT, 4 bytes)
    # -----------------------------
    phase_a_angle = Column(F32)
    phase_b_angle = Column(F32)
    phase_c_angle = Column(F32)
    vta_vtb_angle = Column(F32)
    vta_vtc_angle = Column(F32)

    # -----------------------------
    # 3 Phase Watts / Vars / VA (FLOAT, 4 bytes)
    # -----------------------------
    phase_a_watts = Column(F32)
    phase_b_watts = Column(F32)
    phase_c_watts = Column(F32)

    phase_a_vars = Column(F32)
    phase_b_vars = Column(F32)
    phase_c_vars = Column(F32)

    phase_a_va = Column(F32)
    phase_b_va = Column(F32)
    phase_c_va = Column(F32)

    # -----------------------------
    # Power / Frequency (FLOAT, 4 bytes)
    # -----------------------------
    power_factor = Column(F32)
    frequency = Column(F32)

    # -----------------------------
    # Energy Import (DOUBLE, 8 bytes)
    # -----------------------------
    rate_1_import_kwh = Column(F64)
    rate_2_import_kwh = Column(F64)
    rate_3_import_kwh = Column(F64)
    total_import_kwh = Column(F64)
    total_import_kvar = Column(F64)

    # -----------------------------
    # Energy Export (DOUBLE, 8 bytes)
    # -----------------------------
    rate_1_export_kwh = Column(F64)
    rate_2_export_kwh = Column(F64)
    rate_3_export_kwh = Column(F64)
    total_export_kwh = Column(F64)
    total_export_kvar = Column(F64)

    # -----------------------------
    # THD (FLOAT, 4 bytes)
    # -----------------------------
    thd_voltage_a = Column(F32)
    thd_voltage_b = Column(F32)
    thd_voltage_c = Column(F32)
    thd_current_a = Column(F32)
    thd_current_b = Column(F32)
    thd_current_c = Column(F32)

    # -----------------------------
    # Totals (FLOAT, 4 bytes)
    # -----------------------------
    p_total = Column(F32)
    q_total = Column(F32)
    s_total = Column(F32)

    # -----------------------------
    # Ratios (FLOAT, 4 bytes)
    # -----------------------------
    ct_ratio_primary = Column(F32)
    ct_ratio_secondary = Column(F32)
    vt_ratio_primary = Column(F32)
    vt_ratio_secondary = Column(F32)

    # -----------------------------
    # Diagnostics / Demand
    # -----------------------------
    error_code = Column(String(50))  # or String(16) if fixed to meter encoding
    max_demand_kwh_import = Column(F64)
    max_demand_kwh_export = Column(F64)

    # -----------------------------
    # Meter Information
    # -----------------------------
    meter_serial_number = Column(String(32))  # you indicated ValueLen=11 bytes; store as text
    current_date = Column(Date)
    current_time = Column(Time)
    meter_date_time = Column(DateTime(timezone=False))  # device-local datetime if not UTC

    __table_args__ = (
        Index("ix_reading_wide_meter_time", "meter_id", "time_stamp_utc"),
        Index("ix_reading_wide_time", "time_stamp_utc"),
    )


class ProfileReadingValue(Base):
    """
    Table for 30-minute load survey/profile records (e.g. EDMI LS03).
    Matches table name: meter_profile
    """
    __tablename__ = "meter_profile"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    meter_id = Column(Integer, ForeignKey("meters.id", ondelete="CASCADE"), nullable=False)
    meter = relationship("Meter", back_populates="profile_reading_values")

    # Timestamp of the profile record (from LS03 "time_stamp")
    time_stamp = Column(DateTime(timezone=False), nullable=False)

    # LS03 "Record Status" (0.0 means valid interval record)
    record_status = Column(F64, nullable=True)

    # LS03 cumulative totals (use same meaning as your LS03 keys)
    total_energy_tot_imp_wh = Column(F64, nullable=True)  # "Total Energy Tot IMP Wh @"
    total_energy_tot_exp_wh = Column(F64, nullable=True)  # "Total Energy Tot EXP Wh @"
    total_energy_tot_imp_va = Column(F64, nullable=True)  # "Total Energy Tot IMP va @"
    total_energy_tot_exp_va = Column(F64, nullable=True)  # "Total Energy Tot EXP va @"

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("meter_id", "time_stamp", name="uq_meter_profile_meter_time"),
        Index("ix_meter_profile_meter_time", "meter_id", "time_stamp"),
        Index("ix_meter_profile_time", "time_stamp"),
    )


class ProfileReadGap(Base):
    """
    Persists missed 30-minute profile-read windows so they can be retried
    when the meter comes back online.  Survives service restarts.
    """
    __tablename__ = "profile_read_gaps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    meter_id = Column(
        Integer,
        ForeignKey("meters.id", ondelete="CASCADE"),
        nullable=False,
    )

    from_dt = Column(DateTime(timezone=False), nullable=False)
    to_dt   = Column(DateTime(timezone=False), nullable=False)

    # pending  →  done | failed
    status = Column(String(20), nullable=False, default="pending")

    retry_count = Column(Integer, nullable=False, default=0)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("meter_id", "from_dt", "to_dt", name="uq_profile_gap_meter_window"),
        Index("ix_profile_gap_meter_status", "meter_id", "status"),
    )