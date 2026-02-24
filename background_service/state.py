from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Keys:
    stop_flag: str = "edmi_app:celery:stop"
    task_id: str = "edmi_app:celery:task_id"
    pause_flag: str = "edmi_app:celery:pause"
    paused_ack: str = "edmi_app:celery:paused_ack"
    profile_request: str = "edmi_app:celery:profile_request"
    profile_response_prefix: str = "edmi_app:celery:profile_response"

    # Pub/Sub channel only
    prelogin_done: str = "edmi_app:celery:prelogin_done"

    # Durable per-task state
    functional_ids_prefix: str = "edmi_app:celery:functional_ids"
    prelogin_done_key_prefix: str = "edmi_app:celery:prelogin_done_key"

    # Meter status SSE stream
    meter_status_channel_prefix: str = "edmi_app:celery:meter_status_channel"
    meter_status_list_prefix: str = "edmi_app:celery:meter_status_list"
    meter_status_seq_prefix: str = "edmi_app:celery:meter_status_seq"

    # Scheduler state (replaces ad-hoc IPC flags)
    scheduler_loop_task_id_prefix: str = "edmi_app:scheduler:loop_task_id"
    scheduler_loop_control_prefix: str = "edmi_app:scheduler:loop_control"
    scheduler_loop_state_prefix: str = "edmi_app:scheduler:loop_state"
    scheduler_loop_priority_prefix: str = "edmi_app:scheduler:loop_priority"
    scheduler_queue_prefix: str = "edmi_app:scheduler:queue"
    scheduler_task_prefix: str = "edmi_app:scheduler:task"
    scheduler_task_result_prefix: str = "edmi_app:scheduler:task_result"
    scheduler_prelogin_done_prefix: str = "edmi_app:scheduler:prelogin_done"
    scheduler_functional_ids_prefix: str = "edmi_app:scheduler:functional_ids"
    scheduler_singleflight_prefix: str = "edmi_app:scheduler:singleflight"
