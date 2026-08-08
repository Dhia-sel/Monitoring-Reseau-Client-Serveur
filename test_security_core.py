"""
Tests unitaires pour security_core.py (détecteur scan/flood + blocage).

Contrairement à test_suite.py, ces tests n'ont pas besoin du serveur TCP/TLS
en marche : ils appellent directement les fonctions de security_core.
On patche les seuils en mémoire (plus rapides/petits) pour ne pas attendre
de vraies fenêtres de 1s/10s à chaque test.
"""
import time

import security_core


def _reset(flood_warn=3, flood_block=6, block_duration=1,
           probe_max_duration=0.5, probe_window=5, probe_threshold=3):
    security_core.reset_state_for_tests()
    security_core.FLOOD_THRESHOLD_WARN = flood_warn
    security_core.FLOOD_THRESHOLD_BLOCK = flood_block
    security_core.BLOCK_DURATION = block_duration
    security_core.SCAN_PROBE_MAX_DURATION = probe_max_duration
    security_core.SCAN_PROBE_WINDOW = probe_window
    security_core.SCAN_PROBE_THRESHOLD = probe_threshold


def test_1_flood_blocks_after_threshold():
    _reset()
    addr = '10.0.0.1:1111'
    blocked = False
    for _ in range(6):
        blocked = security_core.register_connection_open(addr)
    ok = blocked and security_core.is_blocked(addr)
    print(f"[Test 1] Flood block after threshold: {'OK' if ok else 'FAIL'}")
    return ok


def test_2_low_rate_does_not_block():
    _reset()
    addr = '10.0.0.2:1111'
    blocked_any = False
    for _ in range(2):
        if security_core.register_connection_open(addr):
            blocked_any = True
    ok = (not blocked_any) and (not security_core.is_blocked(addr))
    print(f"[Test 2] Low rate stays unblocked: {'OK' if ok else 'FAIL'}")
    return ok


def test_3_block_expires_after_duration():
    _reset(block_duration=1)
    addr = '10.0.0.3:1111'
    for _ in range(6):
        security_core.register_connection_open(addr)
    was_blocked = security_core.is_blocked(addr)
    time.sleep(1.2)
    ok = was_blocked and (not security_core.is_blocked(addr))
    print(f"[Test 3] Block expires after duration: {'OK' if ok else 'FAIL'}")
    return ok


def test_4_scan_detected_on_repeated_zero_byte_probes():
    _reset(probe_threshold=3, probe_max_duration=0.5)
    addr = '10.0.0.4:1111'
    blocked = False
    for _ in range(3):
        blocked = security_core.register_connection_close(addr, bytes_transferred=0, duration_s=0.05)
    ok = blocked and security_core.is_blocked(addr)
    print(f"[Test 4] Scan detected on repeated zero-byte probes: {'OK' if ok else 'FAIL'}")
    return ok


def test_5_normal_traffic_not_classified_as_scan():
    _reset(probe_threshold=3)
    addr = '10.0.0.5:1111'
    blocked_any = False
    for _ in range(5):
        # Connexions avec des données réelles échangées : pas des sondes.
        if security_core.register_connection_close(addr, bytes_transferred=2048, duration_s=1.5):
            blocked_any = True
    ok = (not blocked_any) and (not security_core.is_blocked(addr))
    print(f"[Test 5] Normal traffic not flagged as scan: {'OK' if ok else 'FAIL'}")
    return ok


def test_6_slow_zero_byte_connection_not_a_probe():
    _reset(probe_max_duration=0.5, probe_threshold=3)
    addr = '10.0.0.6:1111'
    blocked_any = False
    for _ in range(5):
        # 0 octet mais connexion longue (ex. client qui garde la connexion
        # ouverte sans rien envoyer) : ce n'est pas une signature de scan.
        if security_core.register_connection_close(addr, bytes_transferred=0, duration_s=2.0):
            blocked_any = True
    ok = not blocked_any
    print(f"[Test 6] Slow zero-byte connection is not treated as a probe: {'OK' if ok else 'FAIL'}")
    return ok


def test_7_fail_open_on_security_core_exception():
    """Vérifie le comportement fail-open : si security_core lève une
    exception (bug, corruption d'état...), le code appelant doit continuer
    à laisser passer le trafic plutôt que de bloquer un client légitime.
    On simule ça comme le fait proxy.py, avec un try/except autour de l'appel."""
    def broken_check(addr_str):
        raise RuntimeError("simulated failure")

    original = security_core.register_connection_open
    security_core.register_connection_open = broken_check
    try:
        should_close = False
        try:
            if security_core.is_blocked('10.0.0.7:1111') or security_core.register_connection_open('10.0.0.7:1111'):
                should_close = True
        except Exception:
            pass  # fail-open : on ignore l'erreur, la connexion continue
        ok = should_close is False
        print(f"[Test 7] Fail-open on detector exception: {'OK' if ok else 'FAIL'}")
        return ok
    finally:
        security_core.register_connection_open = original


def run_all_tests():
    print("\n\n")
    print("#" * 60)
    print("# SECURITY CORE - TEST SUITE (scan/flood detector)")
    print("#" * 60 + "\n")

    results = {
        "Test 1: Flood blocks after threshold": test_1_flood_blocks_after_threshold(),
        "Test 2: Low rate stays unblocked": test_2_low_rate_does_not_block(),
        "Test 3: Block expires after duration": test_3_block_expires_after_duration(),
        "Test 4: Scan detected (zero-byte probes)": test_4_scan_detected_on_repeated_zero_byte_probes(),
        "Test 5: Normal traffic not flagged as scan": test_5_normal_traffic_not_classified_as_scan(),
        "Test 6: Slow zero-byte connection is not a probe": test_6_slow_zero_byte_connection_not_a_probe(),
        "Test 7: Fail-open on detector exception": test_7_fail_open_on_security_core_exception(),
    }

    print("\n\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for name, result in results.items():
        status = "OK PASSED" if result else "FAILED"
        print(f"{status}: {name}")

    total = len(results)
    passed = sum(1 for r in results.values() if r)
    print(f"\nTotal: {passed}/{total} tests passed")
    print("=" * 60 + "\n")


if __name__ == '__main__':
    run_all_tests()