from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import sys
import os

# Add the parent directory (project root) to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import Engine, create_engine, text

from runtime_settings import DATABASE_URL
from model.models import Base
from db_utils.db_utils import ensure_default_admin


@dataclass(frozen=True)
class MonthKey:
    year: int
    month: int


def _normalize_to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _month_floor(dt: datetime) -> MonthKey:
    dt = _normalize_to_utc(dt)
    return MonthKey(dt.year, dt.month)


def _add_month(mk: MonthKey) -> MonthKey:
    return MonthKey(mk.year + 1, 1) if mk.month == 12 else MonthKey(mk.year, mk.month + 1)


def _iter_months(start: MonthKey, end: MonthKey) -> Iterable[MonthKey]:
    cur = start
    while (cur.year, cur.month) < (end.year, end.month):
        yield cur
        cur = _add_month(cur)


def _month_start_utc(mk: MonthKey) -> datetime:
    return datetime(mk.year, mk.month, 1, tzinfo=timezone.utc)


def _partition_name(parent_table: str, mk: MonthKey) -> str:
    return f"{parent_table}_{mk.year:04d}_{mk.month:02d}"


def init_time_partition(engine: Engine, start_dt: datetime, end_dt: datetime, *, parent_table: str = "reading_values") -> None:
    st_mk = _month_floor(start_dt)
    et_mk = _month_floor(end_dt)

    if (st_mk.year, st_mk.month) >= (et_mk.year, et_mk.month):
        return

    ddls: list[str] = []
    for mk in _iter_months(st_mk, et_mk):
        next_mk = _add_month(mk)
        part = _partition_name(parent_table, mk)

        start_ts = _month_start_utc(mk).isoformat()
        end_ts = _month_start_utc(next_mk).isoformat()

        ddls.append(
            f"""
            CREATE TABLE IF NOT EXISTS {part}
            PARTITION OF {parent_table}
            FOR VALUES FROM ('{start_ts}') TO ('{end_ts}');
            """.strip()
        )

    with engine.begin() as conn:
        for ddl in ddls:
            conn.execute(text(ddl))


def main() -> None:
    engine = create_engine(DATABASE_URL, future=True, echo=True)

    Base.metadata.create_all(engine)
    ensure_default_admin(engine)

    engine.dispose()


if __name__ == "__main__":
    main()
