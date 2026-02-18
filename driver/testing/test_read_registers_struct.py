from driver.transport.serial_transport import SerialTransport
from driver.serial_settings import PORT, BAUD, TIMEOUT_S
import serial
import time

from driver.frames_codec.login_frame import edmi_begin_init_packet,  edmi_post_process, \
    edmi_create_login_packet, edmi_parse_login_answer
from driver.frames_codec.generics import edmi_validate_crc, edmi_pre_process, wake_up_seq

from driver.meters_config import SERIAL_NUMBER
from driver.utils import bytes_to_hex, combine_packets
from driver.edmi_enums import EDMI_REGISTER, EDMI_TYPE
from driver.frames_codec.read_registers_frame import edmi_create_read_registers_packet,\
    edmi_parse_read_registers_answer
from driver.interface.edmi_structs import EDMIRegister, EDMIRegisterFactory
from typing import List

from driver.edmi_enums import EDMI_COMMAND_TYPE, EDMI_COMMAND_EXTENSION, EDMI_ERROR_CODE

def main() -> None:
    t_start = time.perf_counter()

    ser = serial.Serial(
        port=PORT,
        baudrate=BAUD,
        timeout=TIMEOUT_S,
        write_timeout=TIMEOUT_S,
        exclusive=True
    )
    transport = SerialTransport(ser=ser)

    try:
        # regs = (
        #     EDMI_REGISTER.PHASE_A_VOLTAGE,
        #     EDMI_REGISTER.PHASE_B_VOLTAGE,
        #     EDMI_REGISTER.PHASE_C_VOLTAGE,

        #     # EDMI_REGISTER.PHASE_A_CURRENT,
        #     # EDMI_REGISTER.PHASE_B_CURRENT,
        #     # EDMI_REGISTER.PHASE_C_CURRENT,

        #     # EDMI_REGISTER.POWER_FACTOR,
        #     # EDMI_REGISTER.FREQUENCY,
        # )
        regs: List[EDMIRegister] = [
            EDMIRegisterFactory.CreatePhaseCVoltageRegister(),
            EDMIRegisterFactory.CreatePhaseAVoltageRegister(),
            EDMIRegisterFactory.CreatePhaseBVoltageRegister(),
            EDMIRegister(
                Name="Phase A Current Register",
                Address=EDMI_REGISTER.PHASE_A_CURRENT,
                Type=EDMI_TYPE.FLOAT,
                UnitCode=None,
                ErrorCode=None,
                Value=None
            )
        ]
        wake_up = wake_up_seq()
        login_packet = edmi_create_login_packet(
            username="EDMI",
            password="IMDEIMDE",
            serial=251308613
        )
        read_regs_packet = edmi_create_read_registers_packet(SERIAL_NUMBER, [reg.Address for reg in regs])
        wlogin_packet = combine_packets(wake_up, login_packet)

        transport.connect()

        # --- measure write ---
        t_write_start = time.perf_counter()
        transport.write_packet(wlogin_packet)
        print(f"TX <- {bytes_to_hex(wlogin_packet)}")
        t_write_end = time.perf_counter()

        # --- measure read ---

        received = transport.read_edmi_packet()
        payload = edmi_pre_process(received)
        if EDMI_ERROR_CODE.NONE != edmi_validate_crc(payload):
            raise Exception("Data corrupted. CRC not match")
        t_read_end = time.perf_counter()
        if edmi_parse_login_answer(payload) == EDMI_ERROR_CODE.NONE :
            t_read_start = time.perf_counter()
            transport.write_packet((read_regs_packet))
            print(f"TX <- {bytes_to_hex(read_regs_packet)}")
            received = transport.read_edmi_packet()
            t_read_end = time.perf_counter()
            payload = edmi_pre_process(received)
            if EDMI_ERROR_CODE.NONE != edmi_validate_crc(payload):
                raise Exception("Data corrupted. CRC not match")
            print(f"RX <- {bytes_to_hex(payload)}")
            print(f"read time  : {(t_read_end - t_read_start) * 1e3:.3f} ms")

            parse_err = edmi_parse_read_registers_answer(payload, regs)

            if parse_err != EDMI_ERROR_CODE.NONE:
                print(f"Register parse failed: {parse_err}")
            else:
                print("Parsed register values:")
                for r in regs:
                    if r.ErrorCode == 0x00:
                        print(f" {r.Name}  0x{r.Address:04X} -> {r.Value}")
                    else:
                        print(f" {r.Name} 0x{r.Address:04X} -> ERROR 0x{r.ErrorCode:02X}")

                    print(f"write time : {(t_write_end - t_write_start) * 1e3:.3f} ms")


    except Exception as e:
        raise e
    
    finally:
        transport.disconnect()

        t_end = time.perf_counter()
        print(f"total time : {(t_end - t_start) * 1e3:.3f} ms")


if __name__ == "__main__":
    main()
