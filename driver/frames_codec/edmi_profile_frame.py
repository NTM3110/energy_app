from __future__ import annotations

from datetime import datetime

from driver.interface.edmi_structs import (
    EDMIDateTime,
    EDMIFileInfo,
    EDMIReadFile,
    EDMISearchFile,
    EDMISearchFileDir,
)


def edmi_coerce_datetime(value: datetime | EDMIDateTime) -> EDMIDateTime:
    if isinstance(value, EDMIDateTime):
        return value
    if isinstance(value, datetime):
        return EDMIDateTime(
            Year=value.year % 100,
            Month=value.month,
            Day=value.day,
            Hour=value.hour,
            Minute=value.minute,
            Second=value.second,
            IsNull=False,
        )
    raise TypeError("from/to datetime must be datetime or EDMIDateTime")


def edmi_build_search(
    file_info: EDMIFileInfo,
    dt: datetime | EDMIDateTime,
    direction: EDMISearchFileDir = EDMISearchFileDir.EDMI_SEARCH_FILE_DIR_FORM_START_RECORD_BACKWARD,
) -> EDMISearchFile:
    return EDMISearchFile(
        StartRecord=file_info.StartRecord,
        DateTime=edmi_coerce_datetime(dt),
        DirOrResult=direction,
    )


def edmi_build_read(
    file_info: EDMIFileInfo,
    start_record: int,
    records_count: int,
) -> EDMIReadFile:
    return EDMIReadFile(
        StartRecord=start_record,
        RecordsCount=records_count,
        RecordOffset=0,
        RecordSize=file_info.RecordSize,
    )
