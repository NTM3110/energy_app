# background_service/celery_app.py
from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
from background_service.providers import init_engine
from sqlalchemy import create_engine
from runtime_settings import REDIS_URL, DATABASE_URL

celery_app = Celery("edmi_app", broker=REDIS_URL, backend=REDIS_URL)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)

@worker_process_init.connect
def _init_worker(**_kwargs) -> None:
    engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    future=True,
    )
    init_engine(engine)
    # Runs in the Celery worker process; start the serial owner here.
    from background_service.serial_owner import start_serial_owner
    start_serial_owner()

@worker_process_shutdown.connect
def _shutdown_worker(**_kwargs) -> None:
    from background_service.serial_owner import stop_serial_owner
    stop_serial_owner()

import background_service.tasks  # noqa: E402,F401
