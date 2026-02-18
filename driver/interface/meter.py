from driver.interface.media import Media
from driver.interface.edmi_structs import EDMIRegisterFactory
class Meter:
    def __init__(self,
        username,
        password,
        serial_number,
        media
    ):
        self.username = username
        self.password = password
        self.serial_number = serial_number,
        self.media = media
        self.regs = None
        self._session = None  # auth/session state

    def init_all_registers(self):
        self.regs = (
            # Multipliers / Divisors
            EDMIRegisterFactory.CreateCurrentMultiplierRegister(),
            EDMIRegisterFactory.CreateVoltageMultiplierRegister(),
            EDMIRegisterFactory.CreateCurrentDivisorRegister(),
            EDMIRegisterFactory.CreateVoltageDivisorRegister(),

            # Voltages
            EDMIRegisterFactory.CreatePhaseAVoltageRegister(),
            EDMIRegisterFactory.CreatePhaseBVoltageRegister(),
            EDMIRegisterFactory.CreatePhaseCVoltageRegister(),

            # Currents
            EDMIRegisterFactory.CreatePhaseACurrentRegister(),
            EDMIRegisterFactory.CreatePhaseBCurrentRegister(),
            EDMIRegisterFactory.CreatePhaseCCurrentRegister(),

            # Angles
            EDMIRegisterFactory.CreatePhaseAAngleRegister(),
            EDMIRegisterFactory.CreatePhaseBAngleRegister(),
            EDMIRegisterFactory.CreatePhaseCAngleRegister(),
            EDMIRegisterFactory.CreateVtaVtbAngleRegister(),
            EDMIRegisterFactory.CreateVtaVtcAngleRegister(),

            # Watts
            EDMIRegisterFactory.CreatePhaseAWattsRegister(),
            EDMIRegisterFactory.CreatePhaseBWattsRegister(),
            EDMIRegisterFactory.CreatePhaseCWattsRegister(),

            # Vars
            EDMIRegisterFactory.CreatePhaseAVarsRegister(),
            EDMIRegisterFactory.CreatePhaseBVarsRegister(),
            EDMIRegisterFactory.CreatePhaseCVarsRegister(),

            # VA
            EDMIRegisterFactory.CreatePhaseAVaRegister(),
            EDMIRegisterFactory.CreatePhaseBVaRegister(),
            EDMIRegisterFactory.CreatePhaseCVaRegister(),

            # Power / Frequency
            EDMIRegisterFactory.CreatePowerFactorRegister(),
            EDMIRegisterFactory.CreateFrequencyRegister(),

            # Energy Import (double)
            EDMIRegisterFactory.CreateRate1ImportKwhRegister(),
            EDMIRegisterFactory.CreateRate2ImportKwhRegister(),
            EDMIRegisterFactory.CreateRate3ImportKwhRegister(),
            EDMIRegisterFactory.CreateTotalImportKwhRegister(),
            EDMIRegisterFactory.CreateTotalImportKvarRegister(),

            # Energy Export (double)
            EDMIRegisterFactory.CreateRate1ExportKwhRegister(),
            EDMIRegisterFactory.CreateRate2ExportKwhRegister(),
            EDMIRegisterFactory.CreateRate3ExportKwhRegister(),
            EDMIRegisterFactory.CreateTotalExportKwhRegister(),
            EDMIRegisterFactory.CreateTotalExportKvarRegister(),

            # THD
            EDMIRegisterFactory.CreateThdVoltageARegister(),
            EDMIRegisterFactory.CreateThdVoltageBRegister(),
            EDMIRegisterFactory.CreateThdVoltageCRegister(),
            EDMIRegisterFactory.CreateThdCurrentARegister(),
            EDMIRegisterFactory.CreateThdCurrentBRegister(),
            EDMIRegisterFactory.CreateThdCurrentCRegister(),

            # Totals
            EDMIRegisterFactory.CreatePTotalRegister(),
            EDMIRegisterFactory.CreateQTotalRegister(),
            EDMIRegisterFactory.CreateSTotalRegister(),

            # Ratios
            EDMIRegisterFactory.CreateCtRatioPrimaryRegister(),
            EDMIRegisterFactory.CreateCtRatioSecondaryRegister(),
            EDMIRegisterFactory.CreateVtRatioPrimaryRegister(),
            EDMIRegisterFactory.CreateVtRatioSecondaryRegister(),



            # Demand
            EDMIRegisterFactory.CreateMaxDemandKwhImportRegister(),
            EDMIRegisterFactory.CreateMaxDemandKwhExportRegister(),

            # Meter Information
            EDMIRegisterFactory.CreateMeterSerialNumberRegister(),
                        # Diagnostics
            EDMIRegisterFactory.CreateErrorCodeRegister(),
            EDMIRegisterFactory.CreateCurrentDateRegister(),
            EDMIRegisterFactory.CreateCurrentTimeRegister(),
            EDMIRegisterFactory.CreateDateTimeRegister(),
        )



