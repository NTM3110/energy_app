# app/celery_app.py
from celery import Celery

celery_app = Celery(
    "energy_tasks",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1",
)

celery_app.conf.timezone = "UTC"
