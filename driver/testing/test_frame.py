from driver.transport.serial_transport import SerialTransport
from driver.serial_settings import PORT, BAUD, TIMEOUT_S
import serial
import time

from driver.frames_codec.login_frame import edmi_begin_init_packet,  edmi_post_process, \
    edmi_create_login_packet, edmi_parse_login_answer, wake_up_seq
from driver.frames_codec.generics import edmi_validate_crc, edmi_pre_process

from driver.meters_config import SERIAL_NUMBER
from driver.utils import bytes_to_hex, combine_packets

from driver.edmi_enums import EDMI_COMMAND_TYPE, EDMI_COMMAND_EXTENSION

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
        # init_packet = edmi_begin_init_packet(
        #     serial=SERIAL_NUMBER,
        #     command_type=EDMI_COMMAND_TYPE.LOGIN,
        #     command_extension=EDMI_COMMAND_EXTENSION.NO_EXTENSION,
        # )
        wake_up = wake_up_seq()
        login_packet = edmi_create_login_packet(
            username="EDMA",
            password="IMDEIMDE",
            serial=251308613
        )

        wlogin_packet = combine_packets(wake_up, login_packet)

        transport.connect()

        # --- measure write ---
        t_write_start = time.perf_counter()
        transport.write_packet(wlogin_packet)
        print(f"TX <- {bytes_to_hex(wlogin_packet)}")
        t_write_end = time.perf_counter()

        # --- measure read ---
        t_read_start = time.perf_counter()
        received = transport.read_edmi_packet()
        payload = edmi_pre_process(received)
        if not edmi_validate_crc(payload):
            raise Exception("Corrupted data. CRC does not match")
        t_read_end = time.perf_counter()
        print(edmi_parse_login_answer(payload))
        print(f"RX <- {bytes_to_hex(payload)}")

        print(f"write time : {(t_write_end - t_write_start) * 1e3:.3f} ms")
        print(f"read time  : {(t_read_end - t_read_start) * 1e3:.3f} ms")

    except Exception as e:
        raise e
    
    finally:
        transport.disconnect()

        t_end = time.perf_counter()
        print(f"total time : {(t_end - t_start) * 1e3:.3f} ms")


if __name__ == "__main__":
    main()
