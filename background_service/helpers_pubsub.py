from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Optional

import redis


# -------------------------
# Key helpers (per-task)
# -------------------------

def functional_ids_key(keys: Any, task_id: str) -> str:
    return f"{keys.functional_ids_prefix}:{task_id}"


def prelogin_done_key(keys: Any, task_id: str) -> str:
    return f"{keys.prelogin_done_key_prefix}:{task_id}"


# -------------------------
# Small utils
# -------------------------

def _rget_str(r: Any, key: str) -> Optional[str]:
    v = r.get(key)
    if v is None:
        return None
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return v if isinstance(v, str) else str(v)


def _decode_msg_data(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data if isinstance(data, str) else str(data)


def _parse_json_list_int(raw: str) -> list[int]:
    try:
        obj = json.loads(raw)
    except Exception:
        return []
    if not isinstance(obj, list):
        return []
    out: list[int] = []
    for x in obj:
        if isinstance(x, int):
            out.append(x)
        elif isinstance(x, str) and x.isdigit():
            out.append(int(x))
    return out


def publish_prelogin_done(r: Any, channel: str, *, task_id: str) -> None:
    r.publish(channel, json.dumps({"task_id": task_id}, separators=(",", ":")))


def _fastpath(r: Any, keys: Any, task_id: str) -> Optional[list[int]]:
    if _rget_str(r, prelogin_done_key(keys, task_id)) != "1":
        return None
    raw = _rget_str(r, functional_ids_key(keys, task_id)) or "[]"
    return _parse_json_list_int(raw)


# -------------------------
# Pub/Sub listener thread
# -------------------------

def _pubsub_wait_thread(
    redis_url: str,
    *,
    channel: str,
    task_id: str,
    ready_evt: threading.Event,
    ok_evt: threading.Event,
    stop_evt: threading.Event,
) -> None:
    # Create a dedicated client in this thread (do NOT share cross-thread).
    r = redis.Redis.from_url(redis_url, decode_responses=True)

    pubsub = r.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(channel)

    # Signal to the async side that we are subscribed.
    ready_evt.set()

    try:
        # Use a small timeout so stop_evt can break the loop promptly.
        while not stop_evt.is_set():
            msg = pubsub.get_message(timeout=0.2)
            if not msg:
                continue

            data = _decode_msg_data(msg.get("data"))
            if not data:
                continue

            try:
                payload = json.loads(data)
            except Exception:
                continue

            if payload.get("task_id") == task_id:
                ok_evt.set()
                return
    finally:
        try:
            pubsub.unsubscribe(channel)
        except Exception:
            pass
        try:
            pubsub.close()
        except Exception:
            pass


# -------------------------
# Async API: wait for prelogin
# -------------------------

async def wait_prelogin_result_pubsub(
    r: Any,
    keys: Any,
    *,
    task_id: str,
    redis_url: str,
    timeout_s: float = 5.0,
) -> list[int] | None:
    # 1) Fast-path before subscribe
    fast = _fastpath(r, keys, task_id)
    if fast is not None:
        return fast

    ready_evt = threading.Event()
    ok_evt = threading.Event()
    stop_evt = threading.Event()

    # 2) Start listener thread (do NOT share redis client across threads)
    t = asyncio.create_task(
        asyncio.to_thread(
            _pubsub_wait_thread,
            redis_url,
            channel=keys.prelogin_done,
            task_id=task_id,
            ready_evt=ready_evt,
            ok_evt=ok_evt,
            stop_evt=stop_evt,
        )
    )

    try:
        # 3) Ensure subscribed
        await asyncio.wait_for(asyncio.to_thread(ready_evt.wait), timeout=1.0)

        # 4) Race fix: re-check durable latch AFTER subscribe
        fast2 = _fastpath(r, keys, task_id)
        if fast2 is not None:
            return fast2

        # 5) Wait for notify
        await asyncio.wait_for(asyncio.to_thread(ok_evt.wait), timeout=timeout_s)

    except asyncio.TimeoutError:
        return None

    finally:
        # stop thread loop; do not await/cascade cancellation into ASGI
        stop_evt.set()
        t.cancel()  # wrapper task only; underlying thread exits via stop_evt

    # 6) Read durable result
    raw = _rget_str(r, functional_ids_key(keys, task_id)) or "[]"
    return _parse_json_list_int(raw)


def functional_ids_key(keys: Any, task_id: str) -> str:
    return f"{keys.functional_ids_prefix}:{task_id}"

def prelogin_done_key(keys: Any, task_id: str) -> str:
    return f"{keys.prelogin_done_key_prefix}:{task_id}"