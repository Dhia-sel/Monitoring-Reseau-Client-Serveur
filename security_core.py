"""
Détecteur d'anomalies réseau pour proxy.py.

Deux mécanismes distincts, car un scan et un flood n'ont pas la même
signature réseau :

1. Débit de connexions (register_connection_open) : trop de NOUVELLES
   connexions par seconde depuis une même IP = flood / DoS (T1498/T1499).
   Vérifié à l'ouverture de connexion, donc peut bloquer immédiatement.

2. Comportement de la connexion (register_connection_close) : une connexion
   qui s'ouvre, ne transmet AUCUNE donnée, et se referme presque aussitôt est
   la signature d'une sonde de scan (ex. nmap -sT). Plusieurs sondes de ce
   type venant de la même IP en peu de temps = scan de service (T1046).
   Vérifié à la fermeture, car il faut avoir observé le comportement complet.

Toute IP bloquée (flood ou scan) est fermée immédiatement par proxy.py via
is_blocked(). Les appels à ce module depuis proxy.py sont enveloppés dans un
try/except côté appelant : en cas d'erreur ici, le trafic continue de passer
(fail-open) plutôt que de couper un service légitime sur un bug du détecteur.
"""
import json
import threading
import time
from datetime import datetime

import config

EVENTS_FILE = config.EVENTS_FILE

FLOOD_WINDOW = config.FLOOD_WINDOW_SECONDS
FLOOD_THRESHOLD_WARN = config.FLOOD_THRESHOLD_WARN
FLOOD_THRESHOLD_BLOCK = config.FLOOD_THRESHOLD_BLOCK
BLOCK_DURATION = config.BLOCK_DURATION_SECONDS

SCAN_PROBE_MAX_DURATION = config.SCAN_PROBE_MAX_DURATION_SECONDS
SCAN_PROBE_WINDOW = config.SCAN_PROBE_WINDOW_SECONDS
SCAN_PROBE_THRESHOLD = config.SCAN_PROBE_THRESHOLD

MITRE_MAPPING = {
    'FLOOD_DETECTED': 'T1498',
    'SCAN_DETECTED': 'T1046',
}
ALERT_SEVERITY = {
    'FLOOD_DETECTED': 'high',
    'SCAN_DETECTED': 'medium',
}

_lock = threading.Lock()
_connection_timestamps = {}   # addr_str -> [timestamps des connexions ouvertes] (flood)
_probe_timestamps = {}        # addr_str -> [timestamps des sondes 0-octet] (scan)
_blocked_ips = {}              # addr_str -> timestamp de déblocage


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


def _block(addr_str, now):
    _blocked_ips[addr_str] = now + BLOCK_DURATION


def register_connection_open(addr_str):
    """À appeler dès qu'une connexion est acceptée, avant même de contacter
    la cible. Détecte un débit anormal de NOUVELLES connexions (flood/DoS).
    Retourne True si l'IP doit être bloquée/fermée immédiatement."""
    now = time.time()
    should_block = should_warn = False
    with _lock:
        timestamps = _connection_timestamps.setdefault(addr_str, [])
        timestamps.append(now)
        while timestamps and (now - timestamps[0]) > FLOOD_WINDOW:
            timestamps.pop(0)
        count = len(timestamps)
        if count >= FLOOD_THRESHOLD_BLOCK:
            _block(addr_str, now)
            should_block = True
        elif count >= FLOOD_THRESHOLD_WARN:
            should_warn = True

    if should_block:
        record_event('FLOOD_DETECTED', f"{count} conn/s — bloqué {BLOCK_DURATION}s", source_ip=addr_str)
    elif should_warn:
        print(f"[SECURITY][RATE_WARN] {addr_str}: {count} conn/s — surveillance renforcée")
    return should_block


def register_connection_close(addr_str, bytes_transferred, duration_s):
    """À appeler quand une connexion proxifiée se termine, avec le volume
    total transféré (les deux sens confondus) et sa durée en secondes.
    Détecte les sondes typiques d'un scan de service (T1046)."""
    is_probe = bytes_transferred == 0 and duration_s < SCAN_PROBE_MAX_DURATION
    if not is_probe:
        return False

    now = time.time()
    should_block = False
    with _lock:
        timestamps = _probe_timestamps.setdefault(addr_str, [])
        timestamps.append(now)
        while timestamps and (now - timestamps[0]) > SCAN_PROBE_WINDOW:
            timestamps.pop(0)
        count = len(timestamps)
        if count >= SCAN_PROBE_THRESHOLD:
            _block(addr_str, now)
            should_block = True

    if should_block:
        record_event(
            'SCAN_DETECTED',
            f"{count} sondes 0-octet en {SCAN_PROBE_WINDOW:.0f}s — bloqué {BLOCK_DURATION}s",
            source_ip=addr_str,
        )
    return should_block


def reset_state_for_tests():
    with _lock:
        _connection_timestamps.clear()
        _probe_timestamps.clear()
        _blocked_ips.clear()