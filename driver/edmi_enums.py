# types_edmi.py

from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum
from typing import ClassVar
import struct

# -------------------------
# EDMI control identifiers
# -------------------------

EDMI_STX_IDEN = 0x02
EDMI_ETX_IDEN = 0x03
EDMI_DLE_IDEN = 0x10
EDMI_XON_IDEN = 0x11
EDMI_XOFF_IDEN = 0x13
EDMI_IDEN_CORRECTOR = 0x40
EDMI_E_FRAME_IDEN = 0x45

EDMI_MULTI_ERR_IDEN = 0x0000FFF1  # not a byte; keep as int


# -------------------------
# Client serial (wire bytes)
# -------------------------

EDMI_CLIENT_SERIAL_LENGTH = 0x06
EDMI_CLIENT_SERIAL = bytes((0x01, 0x2B, 0x16, 0x68, 0xFF, 0xFF))


# -------------------------
# EDMI enums
# -------------------------

class EDMI_TYPE(IntEnum):
    # Note: these are ASCII codes on the wire (C uses 'A', 'B', etc.)
    STRING = ord("A")                 # Null terminated ASCII string
    BOOLEAN = ord("B")                # 0 false, non-zero true
    BYTE = ord("C")                   # 8-bit unsigned int
    DOUBLE = ord("D")                 # IEEE 64-bit float
    EFA_STRING = ord("E")             # EFA string external; internal hex short
    FLOAT = ord("F")                  # IEEE 32-bit float
    STRING_LONG = ord("G")            # string repr of integer; internal long
    HEX_SHORT = ord("H")              # 16-bit hex unsigned short
    SHORT = ord("I")                  # 16-bit signed short
    VARIABLE_SPACE = ord("J")         # padded with zeros to max
    LONG = ord("L")                   # 32-bit signed long
    NONE = ord("N")                   # invalid type indicator
    FLOAT_ENERGY = ord("O")           # internal u32 micropulses; external float
    POWER_FACTOR = ord("P")           # internal i16; external float (-1..1)
    TIME = ord("Q")                   # internal u32 secs since midnight; ext 3 bytes
    DATE = ord("R")                   # internal u32 secs since 1/1/96; ext 3 bytes
    SPECIAL = ord("S")                # special type
    DATE_TIME = ord("T")              # ext 6 bytes date+time
    DOUBLE_ENERGY = ord("U")          # internal 64-bit micropulses; external double
    LONG_LONG = ord("V")              # 64-bit signed integer
    WAVEFORM = ord("W")               # waveform record
    HEX_LONG = ord("X")               # hex unsigned long
    REGISTER_NUMBER_HEX_LONG = ord("Z")
    SERIAL_NUMBER = ord("M")
    ERROR_STRING = ord("K")


class EDMI_UNIT_CODE(IntEnum):
    AMPS = ord("A")
    LITERS_PER_HOUR = ord("B")
    ANGLE_IN_DEGREES = ord("D")
    CUBIC_METERS_PER_HOUR = ord("G")
    HERTZ = ord("H")
    JOULES_PER_HOUR = ord("I")
    JOULES = ord("J")
    LITERS = ord("L")
    MINUTES = ord("M")
    NO_UNIT = ord("N")
    CUBIC_METERS = ord("O")
    PERCENT = ord("P")
    POWER_FACTOR = ord("Q")
    VARS = ord("R")
    VA = ord("S")
    SECONDS = ord("T")
    UNKNOWN = ord("U")
    VOLTES = ord("V")  # typo preserved from original header
    WATTS = ord("W")
    WATT_HOURS = ord("X")
    VARH = ord("Y")
    VAH = ord("Z")


class EDMI_COMMAND_TYPE(IntEnum):
    # Mixed: one control byte (0x1B) and ASCII letters.
    GET_METER_ATTENTION = 0x1B
    INFO = ord("I")
    READ_REGISTER = ord("R")
    WRITE_REGISTER = ord("W")
    READ_REGISTER_EXTENDED = ord("M")
    WRITE_REGISTER_EXTENDED = ord("N")
    INFO_EXTENDED = ord("O")
    READ_MULTIPLE_REGISTER_EXTENDED = ord("A")
    WRITE_MULTIPLE_REGISTER_EXTENDED = ord("B")
    LOGIN = ord("L")
    LOGOUT = ord("X")
    FILE_ACCESS = ord("F")


class EDMI_COMMAND_EXTENSION(IntEnum):
    NO_EXTENSION = ord("N")
    FILE_READ = ord("R")
    FILE_WRITE = ord("W")
    FILE_INFO = ord("I")
    FILE_SEARCH = ord("S")


class EDMI_RESPONSE_CODE(IntEnum):
    ACK = 0x06
    CAN = 0x18


class EDMI_ERROR_CODE(IntEnum):
    NONE = 0x00
    CAN_NOT_WRITE = 0x01
    UNIMPLEMENTED_OPERATION = 0x02
    REGISTER_NOT_FOUND = 0x03
    ACCESS_DENIED = 0x04
    REQUEST_WRONG_LENGTH = 0x05
    BAD_TYPE_CODE_INTERNAL_ERROR = 0x06
    DATA_NOT_READY_YET = 0x07
    OUT_OF_RANGE = 0x08
    NOT_LOGGED_IN = 0x09
    REQUEST_CRC_ERROR = 0x0A
    RESPONSE_CRC_ERROR = 0x0B
    REQUEST_RESPONSE_COMMAND_MISMATCH = 0x0C
    REQUEST_RESPONSE_REGISTER_MISMATCH = 0x0D
    LOGIN_FAILED = 0x0E
    LOGOUT_FAILED = 0x0F
    GET_METER_ATTENTION_FAILED = 0x10
    RESPONSE_WRONG_LENGTH = 0x11
    UNIMPLEMENTED_DATA_TYPE = 0x12

class EDMI_REGISTER(IntEnum):
    # Multipliers / Divisors
    CURRENT_MULTIPLIER = 0xF700
    VOLTAGE_MULTIPLIER = 0xF701
    CURRENT_DIVISOR   = 0xF702
    VOLTAGE_DIVISOR   = 0xF703

    # Voltages
    PHASE_A_VOLTAGE = 0xE000
    PHASE_B_VOLTAGE = 0xE001
    PHASE_C_VOLTAGE = 0xE002

    # Currents
    PHASE_A_CURRENT = 0xE010
    PHASE_B_CURRENT = 0xE011
    PHASE_C_CURRENT = 0xE012

    # Angles
    PHASE_A_ANGLE = 0xE020
    PHASE_B_ANGLE = 0xE021
    PHASE_C_ANGLE = 0xE022
    VTA_VTB_ANGLE = 0xE023
    VTA_VTC_ANGLE = 0xE024

    # Watts
    PHASE_A_WATTS = 0xE030
    PHASE_B_WATTS = 0xE031
    PHASE_C_WATTS = 0xE032
 
    # Vars
    PHASE_A_VARS = 0xE040
    PHASE_B_VARS = 0xE041
    PHASE_C_VARS = 0xE042   

    # VA
    PHASE_A_VA = 0xE050
    PHASE_B_VA = 0xE051
    PHASE_C_VA = 0xE052   

    # Power / Frequency
    POWER_FACTOR = 0xE026
    FREQUENCY    = 0xE060

    # Energy Import (double)
    RATE_1_IMPORT_KWH = 0x0060
    RATE_2_IMPORT_KWH = 0x0061
    RATE_3_IMPORT_KWH = 0x0062
    TOTAL_IMPORT_KWH  = 0x0069
    TOTAL_IMPORT_KVAR = 0x0269  

    # Energy Export (double)
    RATE_1_EXPORT_KWH = 0x0160
    RATE_2_EXPORT_KWH = 0x0161
    RATE_3_EXPORT_KWH = 0x0162
    TOTAL_EXPORT_KWH  = 0x0169
    TOTAL_EXPORT_KVAR = 0x0369 

    # THD
    THD_VOLTAGE_A = 0x9300
    THD_VOLTAGE_B = 0x9400
    THD_VOLTAGE_C = 0x9500

    THD_CURRENT_A = 0x9000
    THD_CURRENT_B = 0x9100
    THD_CURRENT_C = 0x9200

	# Totals
    P_TOTAL = 0xE033
    Q_TOTAL = 0xE043
    S_TOTAL = 0xE053

	# Ratios
    CT_RATIO_PRIMARY   = 0xF700
    CT_RATIO_SECONDARY = 0xF702
    VT_RATIO_PRIMARY   = 0xF701
    VT_RATIO_SECONDARY = 0xF703

	# Diagnostics
    ERROR_CODE = 0xF016

	# Demand
    MAX_DEMAND_KWH_IMPORT = 0x1069
    MAX_DEMAND_KWH_EXPORT = 0x1169

	# Meter Information
    METER_SERIAL_NUMBER = 0xF002
    CURRENT_DATE        = 0xF010
    CURRENT_TIME        = 0xF011
    DATE_TIME           = 0xF03D

     

def serialize_error(code: EDMI_ERROR_CODE):
    return {
        "Code": int(code),
        "Name": code.name
    }