from __future__ import annotations

import struct
from typing import Union
import binascii
from driver.utils import as_bytes

from driver.edmi_enums import (
    EDMI_STX_IDEN,
    EDMI_E_FRAME_IDEN,
    EDMI_CLIENT_SERIAL,
    EDMI_CLIENT_SERIAL_LENGTH,
    EDMI_COMMAND_TYPE,
    EDMI_COMMAND_EXTENSION,
    EDMI_ERROR_CODE,
    EDMI_RESPONSE_CODE
)

from driver.edmi_enums import (
    EDMI_STX_IDEN, EDMI_ETX_IDEN, EDMI_DLE_IDEN, EDMI_XON_IDEN, EDMI_XOFF_IDEN, EDMI_IDEN_CORRECTOR
)
from driver.frames_codec.generics import edmi_post_process, edmi_begin_init_packet, edmi_end_init_packet,\
    edmi_pre_process, edmi_validate_crc

ESCAPE_SET = {
    EDMI_STX_IDEN,
    EDMI_ETX_IDEN,
    EDMI_XON_IDEN,
    EDMI_XOFF_IDEN,
    EDMI_DLE_IDEN,
}


BytesLike = Union[bytes, bytearray, memoryview]


def edmi_create_login_packet(
    serial: int,
    username: Union[str, BytesLike],
    password: Union[str, BytesLike],
) -> bytes:
    base = edmi_begin_init_packet(
        serial=serial,
        command_type=EDMI_COMMAND_TYPE.LOGIN,
        command_extension=EDMI_COMMAND_EXTENSION.NO_EXTENSION,
    )

    u = as_bytes(username, "ascii")
    p = as_bytes(password, "ascii")

    n_base = len(base)
    n_u = u.nbytes
    n_p = p.nbytes
    total = n_base + n_u + 1 + n_p + 1

    buf = bytearray(total)
    mv = memoryview(buf)

    i = 0
    mv[i:i + n_base] = base; i += n_base
    mv[i:i + n_u] = u; i += n_u
    mv[i] = ord(","); i += 1
    mv[i:i + n_p] = p; i += n_p
    mv[i] = 0x00

    return edmi_end_init_packet(mv)

def edmi_parse_login_answer(payload: BytesLike) -> EDMI_ERROR_CODE:
    """
    Payload is expected to start with the result code byte.
    Success iff first byte == ACK (0x06).
    """
    mv = payload if isinstance(payload, memoryview) else memoryview(payload)
    if mv.nbytes != 16:
        return EDMI_ERROR_CODE.RESPONSE_WRONG_LENGTH
    return EDMI_ERROR_CODE.NONE if mv[12] == EDMI_RESPONSE_CODE.ACK else EDMI_ERROR_CODE.LOGIN_FAILED