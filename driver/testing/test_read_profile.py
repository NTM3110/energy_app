from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta

from driver.edmi_enums import EDMI_ERROR_CODE, EDMI_REGISTER, EDMI_TYPE, EDMI_UNIT_CODE
from driver.frames_codec.generics import edmi_pre_process, edmi_validate_crc, wake_up_seq
from driver.frames_codec.login_frame import edmi_create_login_packet, edmi_parse_login_answer
from driver.frames_codec.read_profile_frame import (
    edmi_create_read_profile_info_access_packet,
    edmi_create_read_profile_packet,
    edmi_create_search_profile_packet,
    edmi_get_file_channel_regs,
    edmi_get_file_info_regs,
    edmi_parse_read_profile_info_access_payload,
    edmi_parse_read_profile_payload,
    edmi_parse_search_profile_payload,
    edmi_set_file_channel_info,
    edmi_set_profile_info,
)
from driver.frames_codec.read_registers_frame import (
    edmi_create_read_registers_packet,
    edmi_parse_read_registers_answer,
)
from driver.interface.edmi_structs import (
    EDMIDateTime,
    EDMIFileChannelInfo,
    EDMIFileInfo,
    EDMIProfileSpec,
    EDMIRegister,
    EDMIReadFile,
    EDMISearchFile,
    EDMISearchFileDir,
    EDMISurvey,
    MAX_VALUE_LENGTH,
)
from driver.meters_config import PASWORD, SERIAL_NUMBER, USERNAME
from driver.serial_settings import BAUD, PORT, TIMEOUT_S
from driver.transport.serial_connector import SerialConfig, SerialConnector
from driver.transport.serial_transport import SerialTransport
from driver.utils import bytes_to_hex, combine_packets


def _edmi_datetime_from_py(dt: datetime) -> EDMIDateTime:
    return EDMIDateTime(
        Year=dt.year % 100,
        Month=dt.month,
        Day=dt.day,
        Hour=dt.hour,
        Minute=dt.minute,
        Second=dt.second,
        IsNull=False,
    )


def _py_datetime_from_edmi_date_time(date_val: tuple, time_val: tuple) -> datetime:
    day, month, year = date_val
    hour, minute, second = time_val
    year_full = 2000 + year
    return datetime(year_full, month, day, hour, minute, second)


async def main() -> None:
    t_start = time.perf_counter()

    cfg = SerialConfig(
        port=PORT,
        baudrate=BAUD,
        timeout_s=TIMEOUT_S,
        write_timeout_s=TIMEOUT_S,
        exclusive=True,
    )
    connector = SerialConnector(cfg)
    connector.start()

    transport = SerialTransport(connector)

    try:
        await transport.wait_ready()

        wake_up = wake_up_seq()
        login_packet = edmi_create_login_packet(
            username=USERNAME,
            password=PASWORD,
            serial=SERIAL_NUMBER,
        )
        wlogin_packet = combine_packets(wake_up, login_packet)

        await transport.write_packet(wlogin_packet)
        print(f"TX <- {bytes_to_hex(wlogin_packet)}")

        received = await transport.read_edmi_packet()
        payload = edmi_pre_process(received)
        print(f"RX <- {bytes_to_hex(payload)}")
        if edmi_validate_crc(payload) != EDMI_ERROR_CODE.NONE:
            raise RuntimeError("Data corrupted. CRC not match")

        login_err = edmi_parse_login_answer(payload)
        if login_err != EDMI_ERROR_CODE.NONE:
            raise RuntimeError(f"Login failed. ERROR: {login_err}")

        survey = EDMISurvey.LS02

        info_regs = edmi_get_file_info_regs(survey)
        info_regs_packet = edmi_create_read_registers_packet(
            SERIAL_NUMBER,
            [reg.Address for reg in info_regs],
        )
        await transport.write_packet(info_regs_packet)
        print(f"TX <- {bytes_to_hex(info_regs_packet)}")

        received = await transport.read_edmi_packet()
        payload = edmi_pre_process(received)
        print(f"RX <- {bytes_to_hex(payload)}")
        if edmi_validate_crc(payload) != EDMI_ERROR_CODE.NONE:
            raise RuntimeError("Data corrupted. CRC not match")

        err = edmi_parse_read_registers_answer(payload, info_regs)
        if err != EDMI_ERROR_CODE.NONE:
            raise RuntimeError(f"Register parse failed: {err}")

        file_info = EDMIFileInfo(
            Interval=0,
            ChannelsCount=0,
            StartRecord=0,
            RecordsCount=0,
            RecordSize=0,
            Type=0,
            Name="",
            ValueLen=MAX_VALUE_LENGTH,
        )
        err = edmi_set_profile_info(file_info, info_regs)
        if err != EDMI_ERROR_CODE.NONE:
            raise RuntimeError(f"Profile info regs failed: {err}")

        info_access_packet = edmi_create_read_profile_info_access_packet(
            SERIAL_NUMBER,
            survey,
        )
        await transport.write_packet(info_access_packet)
        print(f"TX <- {bytes_to_hex(info_access_packet)}")

        received = await transport.read_edmi_packet()
        payload = edmi_pre_process(received)
        print(f"RX <- {bytes_to_hex(payload)}")
        if edmi_validate_crc(payload) != EDMI_ERROR_CODE.NONE:
            raise RuntimeError("Data corrupted. CRC not match")

        err = edmi_parse_read_profile_info_access_payload(payload, file_info)
        if err != EDMI_ERROR_CODE.NONE:
            raise RuntimeError(f"Profile info access failed: {err}")

        channels: list[EDMIFileChannelInfo] = []
        print("########",file_info.ChannelsCount)
        for ch in range(file_info.ChannelsCount):
            ch_regs = edmi_get_file_channel_regs(survey, ch)
            ch_regs_packet = edmi_create_read_registers_packet(
                SERIAL_NUMBER,
                [reg.Address for reg in ch_regs],
            )
            await transport.write_packet(ch_regs_packet)
            print(f"TX <- {bytes_to_hex(ch_regs_packet)}")

            received = await transport.read_edmi_packet()
            payload = edmi_pre_process(received)
            print(f"RX <- {bytes_to_hex(payload)}")
            if edmi_validate_crc(payload) != EDMI_ERROR_CODE.NONE:
                raise RuntimeError("Data corrupted. CRC not match")

            err = edmi_parse_read_registers_answer(payload, ch_regs)
            if err != EDMI_ERROR_CODE.NONE:
                raise RuntimeError(f"Channel regs parse failed: {err}")

            ch_info = EDMIFileChannelInfo(
                Type=0,
                UnitCode=0,
                ScalingCode=0,
                ScalingFactor=0.0,
                Name="",
            )
            err = edmi_set_file_channel_info(ch_info, ch_regs)
            if err != EDMI_ERROR_CODE.NONE:
                raise RuntimeError(f"Channel info failed: {err}")

            channels.append(ch_info)

        profile_spec = EDMIProfileSpec(
            Survey=int(survey),
            Interval=file_info.Interval,
            FromDateTime=EDMIDateTime(0, 0, 0, 0, 0, 0, True),
            ToDateTime=EDMIDateTime(0, 0, 0, 0, 0, 0, True),
            RecordsCount=0,
            ChannelsCount=file_info.ChannelsCount,
            ChannelsInfo=channels,
            Name=file_info.Name,
        )

        # Read meter current date/time so we can search a meaningful window.
        dt_regs = [
            EDMIRegister(
                Name="Current Date",
                Address=EDMI_REGISTER.CURRENT_DATE,
                Type=EDMI_TYPE.DATE,
                UnitCode=EDMI_UNIT_CODE.NO_UNIT,
                ErrorCode=None,
                Value=None,
                ValueLen=3,
            ),
            EDMIRegister(
                Name="Current Time",
                Address=EDMI_REGISTER.CURRENT_TIME,
                Type=EDMI_TYPE.TIME,
                UnitCode=EDMI_UNIT_CODE.NO_UNIT,
                ErrorCode=None,
                Value=None,
                ValueLen=3,
            ),
        ]
        dt_packet = edmi_create_read_registers_packet(
            SERIAL_NUMBER,
            [reg.Address for reg in dt_regs],
        )
        await transport.write_packet(dt_packet)
        print(f"TX <- {bytes_to_hex(dt_packet)}")

        received = await transport.read_edmi_packet()
        payload = edmi_pre_process(received)
        print(f"RX <- {bytes_to_hex(payload)}")
        if edmi_validate_crc(payload) != EDMI_ERROR_CODE.NONE:
            raise RuntimeError("Data corrupted. CRC not match")

        err = edmi_parse_read_registers_answer(payload, dt_regs)
        if err != EDMI_ERROR_CODE.NONE:
            raise RuntimeError(f"Current date/time parse failed: {err}")

        meter_now = _py_datetime_from_edmi_date_time(dt_regs[0].Value, dt_regs[1].Value)
        # Provide explicit test window in this month. Format: YYYY-MM-DD HH:MM:SS
        from_dt_str = "2025-12-05 00:00:00"
        to_dt_str = "2026-01-05 01:00:00"
        from_dt = datetime.strptime(from_dt_str, "%Y-%m-%d %H:%M:%S")
        to_dt = datetime.strptime(to_dt_str, "%Y-%m-%d %H:%M:%S")
        if to_dt <= from_dt:
            raise RuntimeError("to_dt must be after from_dt")
        # If your meter clock is behind/ahead, this helps spot out-of-range windows.
        print(f"Meter now: {meter_now.isoformat(sep=' ')}")
        print(f"Search window: {from_dt.isoformat(sep=' ')} -> {to_dt.isoformat(sep=' ')}")

        from_search = EDMISearchFile(
            StartRecord=file_info.StartRecord,
            DateTime=_edmi_datetime_from_py(from_dt),
            DirOrResult=EDMISearchFileDir.EDMI_SEARCH_FILE_DIR_FORM_START_RECORD_BACKWARD,
        )
        from_packet = edmi_create_search_profile_packet(
            SERIAL_NUMBER,
            survey,
            from_search.StartRecord,
            from_search.DateTime,
            from_search.DirOrResult,
        )
        await transport.write_packet(from_packet)
        print(f"TX <- {bytes_to_hex(from_packet)}")

        received = await transport.read_edmi_packet()
        payload = edmi_pre_process(received)
        print(f"RX <- {bytes_to_hex(payload)}")
        if edmi_validate_crc(payload) != EDMI_ERROR_CODE.NONE:
            raise RuntimeError("Data corrupted. CRC not match")

        err = edmi_parse_search_profile_payload(payload, from_search)
        if err != EDMI_ERROR_CODE.NONE:
            raise RuntimeError(f"Profile search (from) failed: {err}")

        to_search = EDMISearchFile(
            StartRecord=file_info.StartRecord,
            DateTime=_edmi_datetime_from_py(to_dt),
            DirOrResult=EDMISearchFileDir.EDMI_SEARCH_FILE_DIR_FORM_START_RECORD_BACKWARD,
        )
        to_packet = edmi_create_search_profile_packet(
            SERIAL_NUMBER,
            survey,
            to_search.StartRecord,
            to_search.DateTime,
            to_search.DirOrResult,
        )
        await transport.write_packet(to_packet)
        print(f"TX <- {bytes_to_hex(to_packet)}")

        received = await transport.read_edmi_packet()
        payload = edmi_pre_process(received)
        print(f"RX <- {bytes_to_hex(payload)}")
        if edmi_validate_crc(payload) != EDMI_ERROR_CODE.NONE:
            raise RuntimeError("Data corrupted. CRC not match")

        err = edmi_parse_search_profile_payload(payload, to_search)
        if err != EDMI_ERROR_CODE.NONE:
            raise RuntimeError(f"Profile search (to) failed: {err}")

        record_count = to_search.StartRecord - from_search.StartRecord + 1
        if record_count < 1:
            record_count = 1

        read = EDMIReadFile(
            StartRecord=from_search.StartRecord,
            RecordsCount=min(file_info.RecordsCount, record_count),
            RecordOffset=0,
            RecordSize=file_info.RecordSize,
        )

        read_packet = edmi_create_read_profile_packet(
            SERIAL_NUMBER,
            survey,
            read.StartRecord,
            read.RecordsCount,
            read.RecordOffset,
            read.RecordSize,
        )
        await transport.write_packet(read_packet)
        print(f"TX <- {bytes_to_hex(read_packet)}")

        received = await transport.read_edmi_packet()
        payload = edmi_pre_process(received)
        print(f"RX <- {bytes_to_hex(payload)}")
        if edmi_validate_crc(payload) != EDMI_ERROR_CODE.NONE:
            raise RuntimeError("Data corrupted. CRC not match")

        fields, err = edmi_parse_read_profile_payload(payload, read, profile_spec)
        if err != EDMI_ERROR_CODE.NONE:
            raise RuntimeError(f"Profile parse failed: {err}")

        idx = 0
        for record in range(read.RecordsCount):
            print(f"Record {record} @ {read.StartRecord + record}")
            for ch in range(profile_spec.ChannelsCount):
                field = fields[idx]
                idx += 1
                ch_info = profile_spec.ChannelsInfo[ch]
                print(f"  CH{ch} {ch_info.Name} -> {field.Value}")

    finally:
        await connector.stop()
        t_end = time.perf_counter()
        print(f"total time : {(t_end - t_start) * 1e3:.3f} ms")


if __name__ == "__main__":
    asyncio.run(main())
