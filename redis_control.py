# app/redis_control.py
from __future__ import annotations

import os
from dataclasses import dataclass

import redis
from background_service.state import Keys as RedisKeys
from background_service.scheduler import TaskScheduler, LoopControl, LoopState


def get_redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def get_redis_client(redis_url: str | None = None) -> redis.Redis:
    url = redis_url or get_redis_url()
    return redis.Redis.from_url(url, decode_responses=True)


def set_stop_flag_one(r: redis.Redis, keys: RedisKeys = RedisKeys()) -> None:
    """
    Request the running loop task to stop (cooperative stop).
    """
    scheduler = TaskScheduler(r, keys)
    scheduler.stop_loop()


def wipe_state(r: redis.Redis, keys: RedisKeys = RedisKeys()) -> None:
    """
    Ensure no state is carried across runs.
    """
    scheduler = TaskScheduler(r, keys)
    scheduler.clear_loop_task()
    r.delete(keys.scheduler_queue)
    scheduler.set_loop_control(LoopControl.RUN)
    scheduler.set_loop_state(LoopState.STOPPED)
