import csv
import time
from datetime import datetime
import os
import subprocess
import sys
import signal
import socket

from app.db import Base, engine, SessionLocal
from model.models import Meter, MeterReading, IntervalState, EnergySite, EnergySource
from model.models import User
from app.interval_state_builder import build_interval_state
from app.period_builder import build_periods
from app.monthly_aggregator import build_monthly_summary
from app.meter_status_summary_buidler import build_meter_status_summary
from datetime import timedelta
from typing import Mapping, Sequence
from dataclasses import dataclass

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------

CSV_PATH = "demo_lp_2026_01_to_03.csv"
DEMO_SLEEP_SECONDS = 0.1
FAST_MODE = os.getenv("FAST", "0") == "1"

# batch | stream
MODE = os.getenv("MODE", "batch")

INTERVAL_MINUTES = timedelta(minutes=30)


# -------------------------------------------------------------------
# DB INIT
# -------------------------------------------------------------------

def init_db():
    Base.metadata.create_all(engine)


# -------------------------------------------------------------------
# METER SETUP
# -------------------------------------------------------------------

def ensure_meters(db):
    """
    Create demo sites, sources, and meters if they do not exist.
      - 2 EnergySites: factory + destination
      - 2 EnergySources: BESS + RTS
      - 11 Meters (4 BESS, 4 RTS, 1 SELF_USE, 1 GRID_POINT, 1 INTERCONNECT)
    """

    # --- default owner ---
    default_user = db.query(User).first()
    if not default_user:
        default_user = User(name="admin", password_hash="hash")
        db.add(default_user)
        db.commit()

    # --- energy sites ---
    factory = db.query(EnergySite).filter_by(type="ENERGY_FACTORY").first()
    if not factory:
        factory = EnergySite(name="Energy Factory", type="ENERGY_FACTORY")
        db.add(factory)

    dest = db.query(EnergySite).filter_by(type="DEST_FACTORY").first()
    if not dest:
        dest = EnergySite(name="Destination Factory", type="DEST_FACTORY")
        db.add(dest)

    db.flush()  # get IDs before using them

    # --- energy sources ---
    bess = db.query(EnergySource).filter_by(name="BESS").first()
    if not bess:
        bess = EnergySource(name="BESS", cost_per_kwh=0.12)
        db.add(bess)

    rts = db.query(EnergySource).filter_by(name="RTS").first()
    if not rts:
        rts = EnergySource(name="RTS", cost_per_kwh=0.05)
        db.add(rts)

    db.flush()

    # --- meters ---
    # (serial_number, role, source, site, meter_name)
    meter_defs = [
        (253319561, "SOURCE",       bess, factory, "BESS_01"),
        (253319562, "SOURCE",       bess, factory, "BESS_02"),
        (253319563, "SOURCE",       bess, factory, "BESS_03"),
        (253319564, "SOURCE",       bess, factory, "BESS_04"),
        (253319565, "SOURCE",       rts,  factory, "SOLAR_01"),
        (253319566, "SOURCE",       rts,  factory, "SOLAR_02"),
        (253319567, "SOURCE",       rts,  factory, "SOLAR_03"),
        (253319568, "SOURCE",       rts,  factory, "SOLAR_04"),
        (253319569, "SELF_USE",     None, factory, "SELF_01"),
        (253319570, "GRID_POINT",   None, factory, "GRID_01"),
        (253319571, "INTERCONNECT", None, dest,    "DEST_01"),
    ]

    created = 0
    for serial, role, source, site, meter_name in meter_defs:
        exists = db.query(Meter).filter_by(serial_number=serial).first()
        if not exists:
            db.add(Meter(
                serial_number=serial,
                role=role,
                source_id=source.id if source else None,
                site_id=site.id,
                meter_name=meter_name,
                username="EDMI",
                password="IMDEIMDE",
                outstation=12,
                type="EDMI",
                model="Mk6E",
                owner_id=default_user.id,
            ))
            created += 1

    db.commit()

    if created:
        print(f"✔ Created {created} demo meters")
    else:
        print("✔ Demo meters already exist")




# -------------------------------------------------------------------
# DEMO RUN
# -------------------------------------------------------------------

def run_demo():
    db = SessionLocal()

    last_calculated_day = None

    ensure_meters(db)

    current_interval = None
    rows_buffer = []

    print("\n▶ Starting demo ingestion")
    print(f"▶ Data interval = {INTERVAL_MINUTES} minutes")
    print(f"▶ Mode          = {MODE.upper()}")

    if FAST_MODE:
        print("▶ Demo speed    = FAST MODE (no delays)\n")
    else:
        print(f"▶ Demo speed    = 1 interval / {DEMO_SLEEP_SECONDS} seconds\n")

    # ---------------- CSV INGESTION ----------------

    with open(CSV_PATH) as f:
        reader = csv.DictReader(f)

        for row in reader:
            ts = datetime.fromisoformat(row["ts"])
            interval_key = (ts,)

            if current_interval is None:
                current_interval = interval_key

            # New interval → process previous
            if interval_key != current_interval:
                process_interval(db, rows_buffer, *current_interval)

                # STREAM MODE: advance calculation immediately
                if MODE == "stream":
                    y = current_interval[0].year
                    m = current_interval[0].month
                    build_periods(db, y, m)
                    build_monthly_summary(db, y, m)
                    build_meter_status_summary(db, mode="stream")

                print(
                    f"Processed interval "
                    f"{current_interval[0] - INTERVAL_MINUTES} → {current_interval[0]}"
                )

                rows_buffer.clear()
                current_interval = interval_key

                if not FAST_MODE:
                    time.sleep(DEMO_SLEEP_SECONDS)

            rows_buffer.append(row)

        # Last interval
        if rows_buffer:
            process_interval(db, rows_buffer, *current_interval)

            if MODE == "stream":
                ts_start = current_interval[0] - INTERVAL_MINUTES
                y = ts_start.year
                m = ts_start.month
                build_periods(db, y, m)
                build_monthly_summary(db, y, m)
                build_meter_status_summary(db, mode="stream")

            print(
                f"Processed final interval "
                f"{current_interval[0] - INTERVAL_MINUTES} → {current_interval[0]}"
            )

    print("\n▶ Ingestion finished")

    # ---------------- BATCH CALCULATION ----------------

    if MODE == "batch":
        months = (
            db.query(IntervalState.year, IntervalState.month)
            .distinct()
            .order_by(IntervalState.year, IntervalState.month)
            .all()
        )

        print("\n▶ Building calculation periods and monthly summaries")

        for year, month in months:
            print(f"  → {year}-{month:02d}")
            build_periods(db, year, month)
            build_monthly_summary(db, year, month)
            build_meter_status_summary(db, mode="batch")

    db.close()
    print("\n✅ DEMO COMPLETE")


# -------------------------------------------------------------------
# INTERVAL PROCESSING
# -------------------------------------------------------------------

def process_interval(db, rows, ts):
    inserted = 0

    for row in rows:
        meter = db.query(Meter).filter_by(
            meter_name=row["meter_serial"]
        ).first()

        if not meter:
            print(f"⚠ Unknown meter {row['meter_serial']} — skipped")
            continue

        db.add(MeterReading(
            meter_id=meter.id,
            ts=ts,
            import_kwh=float(row["import_kwh"]),
            export_kwh=float(row["export_kwh"]),
        ))
        inserted += 1

    db.commit()

    print(
        f"  ↳ Inserted {inserted} meter readings "
        f"for interval {ts}"
    )

    # Build ONE interval state (atomic in time)
    build_interval_state(db, ts)


# -------------------------------------------------------------------
# SERVER & BACKGROUND SERVICES
# -------------------------------------------------------------------

from redis_control import RedisKeys, get_redis_client, set_stop_flag_one, wipe_state
from background_service.state import Keys

@dataclass(frozen=True)
class Cmd:
    uvicorn: tuple[str, ...]
    celery: tuple[str, ...]


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("REDIS_URL", "redis://localhost:6379/0")
    
    repo_root = os.path.dirname(os.path.abspath(__file__))
    # Ensure current directory is in PYTHONPATH
    env["PYTHONPATH"] = repo_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _truthy_env(env: Mapping[str, str], key: str, default: str = "0") -> bool:
    val = env.get(key, default).strip().lower()
    return val in {"1", "true", "yes", "y", "on"}


def _port_available(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def _scan_delete_patterns(redis_url: str, patterns: Sequence[str]) -> None:
    r = get_redis_client(redis_url)

    chunk: list[bytes | str] = []
    chunk_size = 500

    def _flush() -> None:
        nonlocal chunk
        if not chunk:
            return
        pipe = r.pipeline(transaction=False)
        for k in chunk:
            pipe.delete(k)
        pipe.execute()
        chunk = []

    for pattern in patterns:
        for key in r.scan_iter(match=pattern, count=1000):
            chunk.append(key)
            if len(chunk) >= chunk_size:
                _flush()
    _flush()


def _wipe_known_app_state(redis_url: str) -> None:
    r = get_redis_client(redis_url)
    wipe_state(r, Keys())


def _wipe_celery_artifacts(redis_url: str) -> None:
    try:
        from background_service import celery_app as celery_app_module
        app = getattr(celery_app_module, "celery_app", None) or getattr(celery_app_module, "app", None)
        if app is not None:
            app.control.purge()
    except Exception:
        pass

    patterns = (
        "celery-task-meta-*",
        "celery-taskset-meta-*",
        "_kombu.binding.*",
        "_kombu.*",
        "unacked*",
        "unacked_index*",
        "unacked_mutex*",
    )
    _scan_delete_patterns(redis_url, patterns)


def _wipe_everything(redis_url: str, *, flushdb: bool) -> None:
    r = get_redis_client(redis_url)
    if flushdb:
        r.flushdb()
        return
    _wipe_known_app_state(redis_url)
    _wipe_celery_artifacts(redis_url)


def _start(cmd: Sequence[str], env: Mapping[str, str]) -> subprocess.Popen:
    return subprocess.Popen(tuple(cmd), env=dict(env), start_new_session=True)


def _send_pg(proc: subprocess.Popen, sig: int) -> None:
    if proc.poll() is not None:
        return
    if os.name != "posix":
        try:
            proc.send_signal(sig)
        except ProcessLookupError:
            pass
        return
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass


def _kill_pg(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    _send_pg(proc, signal.SIGKILL)


def _stop(proc: subprocess.Popen, *, term_timeout_s: float, kill_timeout_s: float) -> None:
    if proc.poll() is not None:
        return

    _send_pg(proc, signal.SIGTERM)

    term_deadline = time.monotonic() + term_timeout_s
    while time.monotonic() < term_deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)

    _kill_pg(proc)

    kill_deadline = time.monotonic() + kill_timeout_s
    while time.monotonic() < kill_deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)


def start_server() -> int:
    env = _env()
    redis_url = env["REDIS_URL"]

    host = "0.0.0.0"
    port = 8000
    if not _port_available(host, port):
        sys.stderr.write(f"ERROR: Port {port} is already in use on {host}\n")
        return 1

    try:
        r0 = get_redis_client(redis_url)
        set_stop_flag_one(r0, RedisKeys())
        _wipe_everything(redis_url, flushdb=_truthy_env(env, "WIPE_REDIS_FLUSHDB", default="0"))
    except Exception:
        pass

    # Note: Using 'run:app' because run.py might not be the app entrypoint for uvicorn?
    # EDMI used 'app:app'. energy_app has 'main:app' in start_server (step 41).
    # energy_app/main.py exists (step 12).
    # So 'main:app' is likely correct for energy_app API.
    cmd = Cmd(
        uvicorn=("uvicorn", "main:app", "--host", host, "--port", str(port), "--reload"),
        celery=(
            "celery",
            "-A",
            "background_service.celery_app",
            "worker",
            "--loglevel=INFO",
            "--pool=solo",
            "--concurrency=1",
        ),
    )
    
    uvicorn_p = _start(cmd.uvicorn, env)

    time.sleep(0.3)
    if uvicorn_p.poll() is not None:
        return 1

    celery_p = _start(cmd.celery, env)
    
    def _shutdown(exit_code: int) -> None:
        try:
            r2 = get_redis_client(redis_url)
            set_stop_flag_one(r2, RedisKeys())
            wipe_state(r2, Keys())
        except Exception:
            pass

        _stop(celery_p, term_timeout_s=5.0, kill_timeout_s=2.0)
        _stop(uvicorn_p, term_timeout_s=2.0, kill_timeout_s=2.0)
        sys.exit(exit_code)

    def _handle(_sig: int, _frame: object) -> None:
        _shutdown(0)

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    while True:
        uvicorn_rc = uvicorn_p.poll()
        celery_rc = celery_p.poll()

        if uvicorn_rc is not None:
            _shutdown(uvicorn_rc if uvicorn_rc != 0 else 1)

        if celery_rc is not None:
            _shutdown(celery_rc if celery_rc != 0 else 1)

        time.sleep(0.1)


# -------------------------------------------------------------------
# ENTRYPOINT
# -------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: run.py [demo|serve]")
        sys.exit(1)

    cmd_arg = sys.argv[1]

    if cmd_arg == "demo":
        print("Initializing database (safe to re-run)...")
        init_db()

        print("Running demo...")
        run_demo()

    elif cmd_arg == "serve":
        sys.exit(start_server())

    else:
        print(f"Unknown command: {cmd_arg}")
        sys.exit(1)
