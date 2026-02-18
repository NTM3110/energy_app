from fastapi import FastAPI

from api import data_api, faults, meter_api, meter_user_api
from app.db import engine
from api.energy_api import router as energy_router

app = FastAPI(title="Energy API")

app.state.engine = engine
app.include_router(energy_router, prefix="/api")
app.include_router(faults.router, prefix="/api")
app.include_router(meter_api.router, prefix="/api")
app.include_router(meter_user_api.router, prefix="/api")
app.include_router(data_api.router, prefix="/api")
