from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum
from typing import ClassVar, List
import struct
from driver.edmi_enums import EDMI_TYPE, EDMI_UNIT_CODE, EDMI_REGISTER, EDMI_TYPE


# EDMI Register value length
MAX_VALUE_LENGTH = 25
EDMI_MAX_CHANNELS_COUNT = 16

@dataclass
class EDMIDateTime:
    Year: int
    Month: int
    Day: int
    Hour: int
    Minute: int
    Second: int
    IsNull: bool


@dataclass
class EDMIRegister:
    Name: str
    Address: int
    Type: int
    UnitCode: int
    ErrorCode: int
    Value: str

    ValueLen: int


class EDMISurvey(IntEnum):
    LS01 = 0x0305
    LS02 = 0x0325
    LS03 = 0x0345
    LS04 = 0x0365
    LS05 = 0x0385
    LS06 = 0x0395
    LS07 = 0x03A5
    LS08 = 0x03B5
    LS09 = 0x03C5
    LS10 = 0x03D5


@dataclass
class EDMIFileInfo:
    Interval: int
    ChannelsCount: int
    StartRecord: int
    RecordsCount: int
    RecordSize: int
    Type: int
    Name: str

    ValueLen: int


@dataclass
class EDMIFileChannelInfo:
    Type: int
    UnitCode: int
    ScalingCode: int
    ScalingFactor: float
    Name: str

    ValueLen: ClassVar[int] = MAX_VALUE_LENGTH


class EDMISearchFileDir(IntEnum):
    EDMI_SEARCH_FILE_DIR_FORM_START_RECORD_BACKWARD = 0
    EDMI_SEARCH_FILE_DIR_FORM_START_RECORD_FORWARD = 1


class EDMISearchFileResult(IntEnum):
    EDMI_SEARCH_FILE_RESULT_FOUND_EXACT_MATCH = 0
    EDMI_SEARCH_FILE_RESULT_HIT_END_OF_FILE = 1
    EDMI_SEARCH_FILE_RESULT_FOUND_THE_CLOSEST_MATCH = 2
    EDMI_SEARCH_FILE_RESULT_NO_TIME_STAMP_IN_SURVEY = 3
    EDMI_SEARCH_FILE_RESULT_NO_DATA_RECORDED_IN_SURVEY = 4


@dataclass
class EDMISearchFile:
    StartRecord: int
    DateTime: EDMIDateTime
    DirOrResult: int


@dataclass
class EDMIReadFile:
    StartRecord: int
    RecordsCount: int
    RecordOffset: int
    RecordSize: int


@dataclass
class EDMIFileField:
    Value: str

    ValueLen: ClassVar[int] = MAX_VALUE_LENGTH


@dataclass
class EDMIProfileSpec:
    Survey: int
    Interval: int
    FromDateTime: EDMIDateTime
    ToDateTime: EDMIDateTime
    RecordsCount: int
    ChannelsCount: int
    ChannelsInfo: List[EDMIFileChannelInfo]  # must be length EDMI_MAX_CHANNELS_COUNT
    Name: str

    ValueLen: ClassVar[int] = MAX_VALUE_LENGTH
    MAX_CHANNELS: ClassVar[int] = EDMI_MAX_CHANNELS_COUNT

### Register Object Factory
from dataclasses import dataclass

@dataclass
class EDMIRegisterFactory:
    ###################################################
    # ########## Multipliers / Divisors ################
    def CreateCurrentMultiplierRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Current Multiplier Register",
            Address=EDMI_REGISTER.CURRENT_MULTIPLIER,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateVoltageMultiplierRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Voltage Multiplier Register",
            Address=EDMI_REGISTER.VOLTAGE_MULTIPLIER,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateCurrentDivisorRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Current Divisor Register",
            Address=EDMI_REGISTER.CURRENT_DIVISOR,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateVoltageDivisorRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Voltage Divisor Register",
            Address=EDMI_REGISTER.VOLTAGE_DIVISOR,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    #########################################
    ##########  3 Phase Voltages ############
    def CreatePhaseAVoltageRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase A Voltage Register",
            Address=EDMI_REGISTER.PHASE_A_VOLTAGE,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreatePhaseBVoltageRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase B Voltage Register",
            Address=EDMI_REGISTER.PHASE_B_VOLTAGE,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreatePhaseCVoltageRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase C Voltage Register",
            Address=EDMI_REGISTER.PHASE_C_VOLTAGE,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    #########################################
    ##########  3 Phase Currents ############
    def CreatePhaseACurrentRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase A Current Register",
            Address=EDMI_REGISTER.PHASE_A_CURRENT,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreatePhaseBCurrentRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase B Current Register",
            Address=EDMI_REGISTER.PHASE_B_CURRENT,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreatePhaseCCurrentRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase C Current Register",
            Address=EDMI_REGISTER.PHASE_C_CURRENT,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    #########################################
    ##########  3 Phase Angles ############
    def CreatePhaseAAngleRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase A Angle Register",
            Address=EDMI_REGISTER.PHASE_A_ANGLE,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreatePhaseBAngleRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase B Angle Register",
            Address=EDMI_REGISTER.PHASE_B_ANGLE,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreatePhaseCAngleRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase C Angle Register",
            Address=EDMI_REGISTER.PHASE_C_ANGLE,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateVtaVtbAngleRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="VTA-VTB Angle Register",
            Address=EDMI_REGISTER.VTA_VTB_ANGLE,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateVtaVtcAngleRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="VTA-VTC Angle Register",
            Address=EDMI_REGISTER.VTA_VTC_ANGLE,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    #########################################
    ##########  3 Phase Watts ############
    def CreatePhaseAWattsRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase A Watts Register",
            Address=EDMI_REGISTER.PHASE_A_WATTS,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreatePhaseBWattsRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase B Watts Register",
            Address=EDMI_REGISTER.PHASE_B_WATTS,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreatePhaseCWattsRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase C Watts Register",
            Address=EDMI_REGISTER.PHASE_C_WATTS,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    #########################################
    ##########  3 Phase Vars ############
    def CreatePhaseAVarsRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase A Vars Register",
            Address=EDMI_REGISTER.PHASE_A_VARS,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreatePhaseBVarsRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase B Vars Register",
            Address=EDMI_REGISTER.PHASE_B_VARS,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreatePhaseCVarsRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase C Vars Register",
            Address=EDMI_REGISTER.PHASE_C_VARS,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    #########################################
    ##########  3 Phase VA ############
    def CreatePhaseAVaRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase A VA Register",
            Address=EDMI_REGISTER.PHASE_A_VA,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreatePhaseBVaRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase B VA Register",
            Address=EDMI_REGISTER.PHASE_B_VA,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreatePhaseCVaRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Phase C VA Register",
            Address=EDMI_REGISTER.PHASE_C_VA,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    #############################################
    ############# Power / Frequency #############
    def CreatePowerFactorRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Power Factor Register",
            Address=EDMI_REGISTER.POWER_FACTOR,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateFrequencyRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Frequency Register",
            Address=EDMI_REGISTER.FREQUENCY,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    ##################################################
    ############### Energy Import (double)#############
    def CreateRate1ImportKwhRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Rate 1 Import kWh Register",
            Address=EDMI_REGISTER.RATE_1_IMPORT_KWH,
            Type=EDMI_TYPE.DOUBLE,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=8
        )

    def CreateRate2ImportKwhRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Rate 2 Import kWh Register",
            Address=EDMI_REGISTER.RATE_2_IMPORT_KWH,
            Type=EDMI_TYPE.DOUBLE,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=8
        )

    def CreateRate3ImportKwhRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Rate 3 Import kWh Register",
            Address=EDMI_REGISTER.RATE_3_IMPORT_KWH,
            Type=EDMI_TYPE.DOUBLE,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=8
        )

    def CreateTotalImportKwhRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Total Import kWh Register",
            Address=EDMI_REGISTER.TOTAL_IMPORT_KWH,
            Type=EDMI_TYPE.DOUBLE,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=8
        )

    def CreateTotalImportKvarRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Total Import kVar Register",
            Address=EDMI_REGISTER.TOTAL_IMPORT_KVAR,
            Type=EDMI_TYPE.DOUBLE,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=8
        )

    ##################################################
    ############### Energy Export (double)#############
    def CreateRate1ExportKwhRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Rate 1 Export kWh Register",
            Address=EDMI_REGISTER.RATE_1_EXPORT_KWH,
            Type=EDMI_TYPE.DOUBLE,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=8
        )

    def CreateRate2ExportKwhRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Rate 2 Export kWh Register",
            Address=EDMI_REGISTER.RATE_2_EXPORT_KWH,
            Type=EDMI_TYPE.DOUBLE,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=8
        )

    def CreateRate3ExportKwhRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Rate 3 Export kWh Register",
            Address=EDMI_REGISTER.RATE_3_EXPORT_KWH,
            Type=EDMI_TYPE.DOUBLE,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=8
        )

    def CreateTotalExportKwhRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Total Export kWh Register",
            Address=EDMI_REGISTER.TOTAL_EXPORT_KWH,
            Type=EDMI_TYPE.DOUBLE,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=8
        )

    def CreateTotalExportKvarRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Total Export kVar Register",
            Address=EDMI_REGISTER.TOTAL_EXPORT_KVAR,
            Type=EDMI_TYPE.DOUBLE,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=8
        )

    ##################################################
    #################### THD ##########################
    def CreateThdVoltageARegister() -> EDMIRegister:
        return EDMIRegister(
            Name="THD Voltage A Register",
            Address=EDMI_REGISTER.THD_VOLTAGE_A,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateThdVoltageBRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="THD Voltage B Register",
            Address=EDMI_REGISTER.THD_VOLTAGE_B,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateThdVoltageCRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="THD Voltage C Register",
            Address=EDMI_REGISTER.THD_VOLTAGE_C,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateThdCurrentARegister() -> EDMIRegister:
        return EDMIRegister(
            Name="THD Current A Register",
            Address=EDMI_REGISTER.THD_CURRENT_A,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateThdCurrentBRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="THD Current B Register",
            Address=EDMI_REGISTER.THD_CURRENT_B,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateThdCurrentCRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="THD Current C Register",
            Address=EDMI_REGISTER.THD_CURRENT_C,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    ##################################################
    #################### Totals #######################
    def CreatePTotalRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="P Total Register",
            Address=EDMI_REGISTER.P_TOTAL,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateQTotalRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Q Total Register",
            Address=EDMI_REGISTER.Q_TOTAL,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateSTotalRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="S Total Register",
            Address=EDMI_REGISTER.S_TOTAL,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    ##################################################
    #################### Ratios #######################
    def CreateCtRatioPrimaryRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="CT Ratio Primary Register",
            Address=EDMI_REGISTER.CT_RATIO_PRIMARY,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateCtRatioSecondaryRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="CT Ratio Secondary Register",
            Address=EDMI_REGISTER.CT_RATIO_SECONDARY,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateVtRatioPrimaryRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="VT Ratio Primary Register",
            Address=EDMI_REGISTER.VT_RATIO_PRIMARY,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    def CreateVtRatioSecondaryRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="VT Ratio Secondary Register",
            Address=EDMI_REGISTER.VT_RATIO_SECONDARY,
            Type=EDMI_TYPE.FLOAT,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=4
        )

    ##################################################
    ################## Diagnostics ####################
    def CreateErrorCodeRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Error Code Register",
            Address=EDMI_REGISTER.ERROR_CODE,
            Type=EDMI_TYPE.ERROR_STRING,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=17
        )

    ##################################################
    #################### Demand #######################
    def CreateMaxDemandKwhImportRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Max Demand kWh Import Register",
            Address=EDMI_REGISTER.MAX_DEMAND_KWH_IMPORT,
            Type=EDMI_TYPE.DOUBLE,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=8
        )

    def CreateMaxDemandKwhExportRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Max Demand kWh Export Register",
            Address=EDMI_REGISTER.MAX_DEMAND_KWH_EXPORT,
            Type=EDMI_TYPE.DOUBLE,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=8
        )

    ##################################################
    ################ Meter Information ################
    def CreateMeterSerialNumberRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Meter Serial Number Register",
            Address=EDMI_REGISTER.METER_SERIAL_NUMBER,
            Type=EDMI_TYPE.SERIAL_NUMBER,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=10
        )

    def CreateCurrentDateRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Current Date Register",
            Address=EDMI_REGISTER.CURRENT_DATE,
            Type=EDMI_TYPE.DATE,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=3
        )

    def CreateCurrentTimeRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Current Time Register",
            Address=EDMI_REGISTER.CURRENT_TIME,
            Type=EDMI_TYPE.TIME,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=3
        )

    def CreateDateTimeRegister() -> EDMIRegister:
        return EDMIRegister(
            Name="Date Time Register",
            Address=EDMI_REGISTER.DATE_TIME,
            Type=EDMI_TYPE.DATE_TIME,
            UnitCode=None,
            ErrorCode=None,
            Value=None,
            ValueLen=6
        )
