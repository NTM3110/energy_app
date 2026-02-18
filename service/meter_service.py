from driver.interface.meter import Meter
from driver.transport.serial_transport import SerialTransport
from driver.interface.media import Media
from driver.edmi_enums import EDMI_ERROR_CODE
from utils.utils import format_parsed_profile_data

class MeterService:
    def __init__(self, media: Media):
        self.media = media
        self._cache = {}

    def get_meter(self, serial, username, password) -> Meter:
        key = (serial, username)  # or just serial if creds are fixed
        meter = self._cache.get(key)
        if meter is None:
            meter = Meter(username=username, password=password, serial_number=serial, media=self.media)
            meter.init_all_registers()
            self._cache[key] = meter
        return meter
    
    def login(self, username, password, serial_number):
        return self.media.edmi_login(username, password, serial_number)
    
    def read_all_registers_once(
            self, username, password, serial_number, meter):
        regs = [reg for reg in meter.regs]

        return self.media.edmi_read_registers(
            username=username,
            password=password,
            serial_number=serial_number,
            regs=regs,
            keep_open=False,
            do_login=True
        )

    def read_all_registers_continuously(
            self, username, password, serial_number, meter):
        regs = [reg for reg in meter.regs]
        login_err = self.media.edmi_login(
            serial_number=serial_number,
            username=username,
            password=password,
            keep_open=True
        )
        if login_err != EDMI_ERROR_CODE.NONE:

            return regs, login_err
        return self.media.edmi_read_registers(
            username=username,
            password=password,
            serial_number=serial_number,
            regs=regs,
            keep_open=True,
            do_login=False
        )

    def test_login_meters(self, meters: list[Meter]) -> list[int]:
        return self.media.edmi_test_login_meters(meters)

    def read_profile(
            self,
            username,
            password,
            serial_number,
            survey,
            from_datetime,
            to_datetime,
            max_records=None,
            keep_open=False,
            do_login=True
        ):
        profile_spec, fields, err = self.media.edmi_read_profile(
            username=username,
            password=password,
            serial_number=serial_number,
            survey=survey,
            from_datetime=from_datetime,
            to_datetime=to_datetime,
            max_records=max_records,
            keep_open=keep_open,
            do_login=do_login
        )
        if err != EDMI_ERROR_CODE.NONE:
            return [], err

        return format_parsed_profile_data(profile_spec, fields), err
    

    def read_profile_demo(
            self,
            username,
            password,
            serial_number,
            survey,
            from_datetime,
            to_datetime,
            max_records=None,
            keep_open=False,
            do_login=True
        ):
        profile_spec, fields, err = self.media.edmi_read_profile_demo(
            username=username,
            password=password,
            serial_number=serial_number,
            survey=survey,
            from_datetime=from_datetime,
            to_datetime=to_datetime,
            max_records=max_records,
            keep_open=keep_open,
            do_login=do_login
        )
        if err != EDMI_ERROR_CODE.NONE:
            return [], err

        return format_parsed_profile_data(profile_spec, fields), err
    
