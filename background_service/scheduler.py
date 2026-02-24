from __future__ import annotations

import json
import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import redis

from .state import Keys


@dataclass(frozen=True)
class TaskType:
    LOOP: str = "loop"
    ONCE: str = "once"


@dataclass(frozen=True)
class TaskState:
    QUEUED: str = "queued"
    RUNNING: str = "running"
    COMPLETED: str = "completed"
    FAILED: str = "failed"
    CANCELLED: str = "cancelled"


@dataclass(frozen=True)
class LoopControl:
    RUN: str = "run"
    PAUSE: str = "pause"
    STOP: str = "stop"


@dataclass(frozen=True)
class LoopState:
    STARTING: str = "starting"
    RUNNING: str = "running"
    PAUSED: str = "paused"
    STOPPED: str = "stopped"
    STOPPING: str = "stopping"


@dataclass(frozen=True)
class ScheduledTask:
    task_id: str
    name: str
    task_type: str
    priority: int
    payload: dict[str, Any]
    state: str
    created_at: str
    started_at: str | None
    finished_at: str | None


class TaskScheduler:
    def __init__(self, r: redis.Redis, keys: Keys, loop_name: str = "meter") -> None:
        self.r = r
        self.keys = keys
        self.loop_name = loop_name

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _task_key(self, task_id: str) -> str:
        return f"{self.keys.scheduler_task_prefix}:{task_id}"

    def _task_result_key(self, task_id: str) -> str:
        return f"{self.keys.scheduler_task_result_prefix}:{task_id}"

    def _singleflight_key(self, name: str) -> str:
        return f"{self.keys.scheduler_singleflight_prefix}:{name}"

    def _functional_ids_key(self, task_id: str) -> str:
        return f"{self.keys.scheduler_functional_ids_prefix}:{task_id}"

    def _prelogin_done_key(self, task_id: str) -> str:
        return f"{self.keys.scheduler_prelogin_done_prefix}:{task_id}"

    def _queue_key(self) -> str:
        return f"{self.keys.scheduler_queue_prefix}:{self.loop_name}"

    def _loop_task_id_key(self) -> str:
        return f"{self.keys.scheduler_loop_task_id_prefix}:{self.loop_name}"

    def _loop_control_key(self) -> str:
        return f"{self.keys.scheduler_loop_control_prefix}:{self.loop_name}"

    def _loop_state_key(self) -> str:
        return f"{self.keys.scheduler_loop_state_prefix}:{self.loop_name}"

    def _loop_priority_key(self) -> str:
        return f"{self.keys.scheduler_loop_priority_prefix}:{self.loop_name}"

    def _load_task(self, task_id: str) -> dict[str, Any] | None:
        raw = self.r.get(self._task_key(task_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def _save_task(self, task_id: str, payload: dict[str, Any]) -> None:
        self.r.set(self._task_key(task_id), json.dumps(payload, separators=(",", ":")))

    def get_loop_task_id(self) -> str | None:
        return self.r.get(self._loop_task_id_key())

    def set_loop_control(self, control: str) -> None:
        self.r.set(self._loop_control_key(), control)

    def get_loop_control(self) -> str:
        return self.r.get(self._loop_control_key()) or LoopControl.RUN

    def set_loop_state(self, state: str) -> None:
        self.r.set(self._loop_state_key(), state)

    def get_loop_state(self) -> str:
        return self.r.get(self._loop_state_key()) or LoopState.STOPPED

    def set_loop_priority(self, priority: int) -> None:
        self.r.set(self._loop_priority_key(), str(priority))

    def get_loop_priority(self) -> int:
        raw = self.r.get(self._loop_priority_key())
        if raw is None:
            return 0
        try:
            return int(raw)
        except ValueError:
            return 0

    def register_loop_task(self, task_id: str, *, priority: int) -> bool:
        if self.r.setnx(self._loop_task_id_key(), task_id):
            self.set_loop_control(LoopControl.RUN)
            self.set_loop_state(LoopState.STARTING)
            self.set_loop_priority(priority)
            return True
        return False

    def force_register_loop_task(self, task_id: str, *, priority: int) -> None:
        self.r.set(self._loop_task_id_key(), task_id)
        self.set_loop_control(LoopControl.RUN)
        self.set_loop_state(LoopState.STARTING)
        self.set_loop_priority(priority)

    def clear_loop_task(self) -> None:
        self.r.delete(self._loop_task_id_key())

    def stop_loop(self) -> str | None:
        task_id = self.get_loop_task_id()
        if task_id is None:
            return None
        self.set_loop_control(LoopControl.STOP)
        self.set_loop_state(LoopState.STOPPING)
        self.clear_loop_task()
        self.set_prelogin_result(task_id, [])
        return task_id

    def enqueue_once(
        self,
        *,
        name: str,
        payload: dict[str, Any],
        priority: int,
        singleflight: bool = False,
        singleflight_ttl_s: int = 300,
    ) -> str | None:
        if singleflight:
            if not self.r.set(self._singleflight_key(name), "1", nx=True, ex=singleflight_ttl_s):
                return None

        task_id = uuid.uuid4().hex
        task = {
            "task_id": task_id,
            "name": name,
            "task_type": TaskType.ONCE,
            "priority": int(priority),
            "payload": payload,
            "state": TaskState.QUEUED,
            "created_at": self._now_iso(),
            "started_at": None,
            "finished_at": None,
        }
        self._save_task(task_id, task)

        score = float(priority) * 1_000_000_000.0 + time.time()
        self.r.zadd(self._queue_key(), {task_id: score})
        return task_id

    def has_pending_task(self, name: str) -> bool:
        lock_key = self._singleflight_key(name)
        return self.r.exists(lock_key) == 1

    def has_runnable_task(self, *, max_priority: int) -> bool:
        task_ids = self.r.zrange(self._queue_key(), 0, 0)
        if not task_ids:
            return False
        task = self._load_task(task_ids[0])
        if not task:
            self.r.zrem(self._queue_key(), task_ids[0])
            return False
        return int(task.get("priority", 0)) <= max_priority

    def claim_next_task(self, *, max_priority: int) -> dict[str, Any] | None:
        task_ids = self.r.zrange(self._queue_key(), 0, 0)
        if not task_ids:
            return None
        task_id = task_ids[0]
        task = self._load_task(task_id)
        if not task:
            self.r.zrem(self._queue_key(), task_id)
            return None
        if int(task.get("priority", 0)) > max_priority:
            return None
        if self.r.zrem(self._queue_key(), task_id) == 0:
            return None
        task["state"] = TaskState.RUNNING
        task["started_at"] = self._now_iso()
        self._save_task(task_id, task)
        return task

    def complete_task(self, task_id: str, result: dict[str, Any]) -> None:
        task = self._load_task(task_id)
        if task:
            task["state"] = TaskState.COMPLETED
            task["finished_at"] = self._now_iso()
            self._save_task(task_id, task)
        self.r.set(self._task_result_key(task_id), json.dumps(result, separators=(",", ":")))
        if task and task.get("name"):
            self.r.delete(self._singleflight_key(task["name"]))

    def fail_task(self, task_id: str, error: str) -> None:
        task = self._load_task(task_id)
        if task:
            task["state"] = TaskState.FAILED
            task["finished_at"] = self._now_iso()
            self._save_task(task_id, task)
            if task.get("name"):
                self.r.delete(self._singleflight_key(task["name"]))
        self.r.set(self._task_result_key(task_id), json.dumps({"status": "error", "error": error}))

    def cancel_task(self, task_id: str) -> None:
        self.r.zrem(self._queue_key(), task_id)
        task = self._load_task(task_id)
        if task:
            task["state"] = TaskState.CANCELLED
            task["finished_at"] = self._now_iso()
            self._save_task(task_id, task)
            if task.get("name"):
                self.r.delete(self._singleflight_key(task["name"]))

    def set_prelogin_result(self, task_id: str, functional_ids: list[int]) -> None:
        self.r.set(self._functional_ids_key(task_id), json.dumps(functional_ids, separators=(",", ":")))
        self.r.set(self._prelogin_done_key(task_id), "1")

    def clear_prelogin(self, task_id: str) -> None:
        self.r.delete(self._functional_ids_key(task_id))
        self.r.delete(self._prelogin_done_key(task_id))

    def get_prelogin_result(self, task_id: str) -> list[int] | None:
        if self.r.get(self._prelogin_done_key(task_id)) != "1":
            return None
        raw = self.r.get(self._functional_ids_key(task_id)) or "[]"
        try:
            data = json.loads(raw)
        except Exception:
            return []
        return data if isinstance(data, list) else []

    async def wait_prelogin_result(self, task_id: str, timeout_s: float) -> list[int] | None:
        start = time.monotonic()
        while time.monotonic() - start < timeout_s:
            result = self.get_prelogin_result(task_id)
            if result is not None:
                return result
            await asyncio.sleep(0.05)
        return None

    async def wait_task_result(self, task_id: str, timeout_s: float) -> dict[str, Any] | None:
        start = time.monotonic()
        key = self._task_result_key(task_id)
        while time.monotonic() - start < timeout_s:
            raw = self.r.get(key)
            if raw:
                try:
                    return json.loads(raw)
                except Exception:
                    return {"status": "invalid_response"}
            await asyncio.sleep(0.05)
        return None
