from __future__ import annotations

import asyncio
import time
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from datetime import datetime
from pprint import pformat

from driver.utils import format_parsed_profile_data
from driver.edmi_enums import EDMI_ERROR_CODE, EDMI_TYPE
from driver.interface.media import Media
from driver.interface.edmi_structs import (
    EDMIDateTime,
    EDMIFileChannelInfo,
    EDMIProfileSpec,
    EDMISurvey,
)
from driver.meters_config import PASWORD, SERIAL_NUMBER, USERNAME
from driver.serial_settings import BAUD, PORT, TIMEOUT_S
from driver.transport.serial_connector import SerialConfig, SerialConnector
from driver.transport.serial_transport import SerialTransport

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
    media = Media(serial_transport=transport, debug=True)

    try:
        await transport.wait_ready()

        from_dt_str = "2026-01-18 00:30:00"
        to_dt_str = "2026-01-20 10:00:00"
        from_dt = datetime.strptime(from_dt_str, "%Y-%m-%d %H:%M:%S")
        to_dt = datetime.strptime(to_dt_str, "%Y-%m-%d %H:%M:%S")

        def _call_read_profile():
            print(f"Requested window: {from_dt_str} -> {to_dt_str} (survey {EDMISurvey.LS01.name})")
            channels = [
                EDMIFileChannelInfo(
                    Type=EDMI_TYPE.FLOAT,
                    UnitCode=0,
                    ScalingCode=0,
                    ScalingFactor=1.0,
                    Name=f"CH{idx}",
                )
                for idx in range(EDMIProfileSpec.MAX_CHANNELS)
            ]
            profile_spec = EDMIProfileSpec(
                Survey=int(EDMISurvey.LS01),
                Interval=0,
                FromDateTime=EDMIDateTime(0, 0, 0, 0, 0, 0, True),
                ToDateTime=EDMIDateTime(0, 0, 0, 0, 0, 0, True),
                RecordsCount=0,
                ChannelsCount=len(channels),
                ChannelsInfo=channels,
                Name="",
            )
            return media.edmi_read_profile(
                username=USERNAME,
                password=PASWORD,
                serial_number=SERIAL_NUMBER,
                survey=EDMISurvey.LS03,
                from_datetime=from_dt,
                to_datetime=to_dt,
                max_records=None,
                profile_spec=profile_spec,
                keep_open=True,
                do_login=True,
            )

        profile_spec, fields, err = await asyncio.to_thread(_call_read_profile)
        # if err != EDMI_ERROR_CODE.NONE:
        #     raise RuntimeError(f"Profile read failed: {err}")
        print(
            "Profile metadata:",
            {
                "start_record": getattr(profile_spec, "StartRecord", None),
                "records_count": profile_spec.RecordsCount,
                "interval_sec": profile_spec.Interval,
            },
        )
        
        # records = format_parsed_profile_data(profile_spec, fields)
        # print(records)

        # def _as_pretty(obj):
        #     if is_dataclass(obj):
        #         return {
        #             field.name: _as_pretty(getattr(obj, field.name))
        #             for field in dataclass_fields(obj)
        #         }
        #     if isinstance(obj, list):
        #         return [_as_pretty(item) for item in obj]
        #     if isinstance(obj, dict):
        #         return {key: _as_pretty(value) for key, value in obj.items()}
        #     return obj

        # def _print_section(title: str, payload) -> None:
        #     print(f"##### {title} #####")
        #     print(pformat(payload, width=120, sort_dicts=False))

        # _print_section("PROFILE SPEC", _as_pretty(profile_spec))
        # # _print_section("FIELDS (FLAT LIST)", [_as_pretty(field) for field in fields])

        # if profile_spec.Interval:
        #     interval_min = profile_spec.Interval / 60.0
        #     print(f"Profile Interval: {profile_spec.Interval} seconds ({interval_min:.2f} minutes)")

        # if profile_spec.ChannelsCount == 0:
        #     print("No channels returned")
        #     return

        # print("##### FIELDS (BY RECORD) #####")
        # records_count = profile_spec.RecordsCount or (len(fields) // profile_spec.ChannelsCount)
        # print(records_count)
        # idx = 0
        # for record in range(records_count):
        #     print(f"Record {record}")
        #     for ch in range(profile_spec.ChannelsCount):
        #         field = fields[idx]
        #         idx += 1
        #         ch_info = profile_spec.ChannelsInfo[ch]
        #         print(f"  CH{ch} {ch_info.Name} -> {field.Value}")

    finally:
        await connector.stop()
        t_end = time.perf_counter()
        print(f"total time : {(t_end - t_start) * 1e3:.3f} ms")


if __name__ == "__main__":
    asyncio.run(main())
