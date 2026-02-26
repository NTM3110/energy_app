import redis
import json
import time
from background_service.state import Keys

def monitor_status(task_id):
    r = redis.Redis.from_url("redis://localhost:6379/0", decode_responses=True)
    keys = Keys()
    list_key = f"{keys.meter_status_list_prefix}:{task_id}"
    
    print(f"Monitoring status for task {task_id}...")
    last_len = 0
    while True:
        curr_len = r.llen(list_key)
        if curr_len > last_len:
            for i in range(last_len, curr_len):
                raw = r.lindex(list_key, i)
                if raw:
                    event = json.loads(raw)
                    print(f"Event: {event.get('event')} @ {event.get('data', {}).get('slot_ts')}")
                    for status in event.get('data', {}).get('meter_status', []):
                        print(f"  Meter {status.get('meter_id')}: {status.get('status')} {status.get('error', '')}")
            last_len = curr_len
        time.sleep(1)

if __name__ == "__main__":
    # You'll need a task_id from a running loop
    import sys
    if len(sys.argv) > 1:
        monitor_status(sys.argv[1])
    else:
        print("Usage: python verify_loop.py <task_id>")
