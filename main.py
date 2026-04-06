import logging
import uuid
from contextlib import asynccontextmanager

import redis as redis_lib
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from api import data_api, faults, meter_api, meter_user_api, auth_api
from app.db import engine
from api.energy_api import router as energy_router
from background_service.celery_app import celery_app
from background_service.scheduler import TaskScheduler
from background_service.state import Keys
from model.models import Meter
from runtime_settings import REDIS_URL

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- startup: auto-start the meter read loop ----
    try:
        r = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        keys = Keys()
        scheduler = TaskScheduler(r, keys)

        # Fetch all meters from DB
        with Session(engine) as session:
            all_meters = session.query(Meter).all()

        meter_ids = [m.id for m in all_meters]

        if not meter_ids:
            print("[Auto-start] No meters found in DB, skipping meter loop.")
        else:
            existing_task_id = scheduler.get_loop_task_id()
            
            if existing_task_id:
                print(f"[Auto-start] Meter loop already running (task_id={existing_task_id}), skipping.")
            else:
                task_id = uuid.uuid4().hex
                if scheduler.register_loop_task(task_id, priority=0):
                    celery_app.send_task(
                        "read_and_save_meters_loop_sreaming_status",
                        kwargs={"meter_ids": meter_ids},
                        task_id=task_id,
                    )
                    print(f"[Auto-start] Dispatched meter loop task_id={task_id} for meter_ids={meter_ids}")
                else:
                    print("[Auto-start] Loop already registered by another process, skipping.")
    except Exception as e:
        print(f"[Auto-start] ERROR: Failed to dispatch meter loop on startup: {e}")
        logger.exception("Auto-start: failed to dispatch meter loop on startup.")

    yield  # application runs here


app = FastAPI(title="Energy API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to the frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.engine = engine
app.include_router(energy_router, prefix="/api")
app.include_router(faults.router, prefix="/api")
app.include_router(meter_api.router, prefix="/api")
app.include_router(meter_user_api.router, prefix="/api")
app.include_router(data_api.router, prefix="/api")
app.include_router(auth_api.router, prefix="/api/auth")
