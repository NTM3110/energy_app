# app/providers.py
from __future__ import annotations

import os
import threading
from typing import Any
from sqlalchemy import Engine

_bus_sem = threading.Semaphore(1)
_meter_service: Any | None = None


def init_meter_service(service: Any) -> None:
    global _meter_service
    _meter_service = service


def get_meter_service() -> Any:
    if _meter_service is None:
        raise RuntimeError("meter service not initialized")
    return _meter_service


def get_bus_sem() -> threading.Semaphore:
    return _bus_sem

def init_engine(engine: Engine) -> None:
    global _engine
    _engine = engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("engine not initialized")
    return _engine