import json
import threading
import time
from datetime import datetime

EVENTS_FILE = 'events.jsonl'

FLOOD_WINDOW = 1.0
FLOOD_THRESHOLD_WARN = 10
FLOOD_THRESHOLD_BLOCK = 100
BLOCK_DURATION = 60

MITRE_MAPPING = {
    'FLOOD_DETECTED': 'T1498',
    'SCAN_DETECTED': 'T1046',
}
ALERT_SEVERITY = {
    'FLOOD_DETECTED': 'high',
    'SCAN_DETECTED': 'medium',
}

_lock = threading.Lock()
_connection_timestamps = {}
_blocked_ips = {}


def record_event(event_type, message, source_ip=None, agent_id=None):
    event = {
        'timestamp': datetime.now().isoformat(),
        'agent_id': agent_id,
        'type': event_type,
        'source_ip': source_ip,
        'severity': ALERT_SEVERITY.get(event_type, 'low'),
        'mitre_technique': MITRE_MAPPING.get(event_type),
        'message': message,
    }
    print(f"[SECURITY][{event_type}] {source_ip}: {message}")
    try:
        with open(EVENTS_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event) + '\n')
    except Exception as e:
        print(f"[EVENTS] Write error: {e}")


def is_blocked(addr_str):
    now = time.time()
    with _lock:
        unblock_time = _blocked_ips.get(addr_str)
        if unblock_time is None:
            return False
        if now >= unblock_time:
            del _blocked_ips[addr_str]
            return False
        return True


def register_connection_activity(addr_str):
    now = time.time()
    should_block = should_warn = False
    with _lock:
        timestamps = _connection_timestamps.setdefault(addr_str, [])
        timestamps.append(now)
        while timestamps and (now - timestamps[0]) > FLOOD_WINDOW:
            timestamps.pop(0)
        count = len(timestamps)
        if count >= FLOOD_THRESHOLD_BLOCK:
            _blocked_ips[addr_str] = now + BLOCK_DURATION
            should_block = True
        elif count >= FLOOD_THRESHOLD_WARN:
            should_warn = True

    if should_block:
        record_event('FLOOD_DETECTED', f"{count} conn/s — blocked {BLOCK_DURATION}s", source_ip=addr_str)
    elif should_warn:
        record_event('SCAN_DETECTED', f"{count} conn/s — suspicious rate", source_ip=addr_str)
    return should_block