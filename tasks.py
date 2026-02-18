# tasks.py
import csv
from datetime import datetime
from app.celery_app import celery_app
from app.db import SessionLocal
from model.models import Meter, MeterReading
from app.interval_state_builder import build_interval_state


@celery_app.task
def ingest_csv(path="demo_data_month.csv"):
    db = SessionLocal()

    current_interval = None

    with open(path) as f:
        reader = csv.DictReader(f)

        for row in reader:
            ts_start = datetime.fromisoformat(row["ts_start"])
            ts_end = datetime.fromisoformat(row["ts_end"])

            interval_key = (ts_start, ts_end)

            if current_interval is None:
                current_interval = interval_key

            if interval_key != current_interval:
                # finalize previous interval
                build_interval_state(db, *current_interval)
                current_interval = interval_key

            meter = db.query(Meter).filter_by(
                serial_number=row["meter_serial"]
            ).first()

            if not meter:
                continue

            db.add(MeterReading(
                meter_id=meter.id,
                ts_start=ts_start,
                ts_end=ts_end,
                import_kwh=float(row["import_kwh"]),
                export_kwh=float(row["export_kwh"]),
            ))

        # last interval
        if current_interval:
            build_interval_state(db, *current_interval)

    db.commit()
    db.close()
