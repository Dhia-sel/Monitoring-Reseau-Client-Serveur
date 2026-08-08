"""
Tests unitaires pour splunk_forwarder.py.

Aucun Splunk réel n'est nécessaire : requests.post est simulé avec de
fausses réponses HTTP. Les fichiers events.jsonl / offset sont des fichiers
temporaires, recréés à chaque test.
"""
import json
import os
import tempfile

import config
import splunk_forwarder


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=''):
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {'code': 0}
        self.text = text

    def json(self):
        return self._json_body


def _write_events(path, events):
    with open(path, 'w', encoding='utf-8') as f:
        for e in events:
            f.write(json.dumps(e) + '\n')


def _temp_paths():
    events_fd, events_path = tempfile.mkstemp(suffix='.jsonl')
    os.close(events_fd)
    offset_path = events_path + '.offset'
    if os.path.exists(offset_path):
        os.remove(offset_path)
    return events_path, offset_path


def _cleanup(*paths):
    for p in paths:
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


def test_1_read_new_events_basic():
    events_path, offset_path = _temp_paths()
    try:
        events = [
            {'timestamp': '2026-08-03T10:00:00', 'type': 'FLOOD_DETECTED', 'source_ip': '1.2.3.4'},
            {'timestamp': '2026-08-03T10:00:01', 'type': 'SCAN_DETECTED', 'source_ip': '5.6.7.8'},
        ]
        _write_events(events_path, events)

        read, new_offset = splunk_forwarder.read_new_events(events_path, 0, max_events=50)
        ok = len(read) == 2 and read[0]['type'] == 'FLOOD_DETECTED' and new_offset > 0
        print(f"[Test 1] Read new events (basic): {'OK' if ok else 'FAIL'}")
        return ok
    finally:
        _cleanup(events_path, offset_path)


def test_2_malformed_line_is_skipped_but_offset_advances():
    events_path, offset_path = _temp_paths()
    try:
        with open(events_path, 'w', encoding='utf-8') as f:
            f.write('{"timestamp": "2026-08-03T10:00:00", "type": "OK"}\n')
            f.write('not valid json\n')
            f.write('{"timestamp": "2026-08-03T10:00:02", "type": "OK2"}\n')

        read, new_offset = splunk_forwarder.read_new_events(events_path, 0, max_events=50)
        ok = len(read) == 2 and read[0]['type'] == 'OK' and read[1]['type'] == 'OK2'
        print(f"[Test 2] Malformed line skipped, valid ones kept: {'OK' if ok else 'FAIL'}")
        return ok
    finally:
        _cleanup(events_path, offset_path)


def test_3_incomplete_trailing_line_not_consumed():
    events_path, offset_path = _temp_paths()
    try:
        with open(events_path, 'w', encoding='utf-8') as f:
            f.write('{"timestamp": "2026-08-03T10:00:00", "type": "OK"}\n')
            f.write('{"timestamp": "2026-08-03T10:00:01", "type": "STILL_WRIT')  # pas de \n

        read, new_offset = splunk_forwarder.read_new_events(events_path, 0, max_events=50)
        ok = len(read) == 1 and read[0]['type'] == 'OK'
        print(f"[Test 3] Incomplete trailing line not consumed: {'OK' if ok else 'FAIL'}")
        return ok
    finally:
        _cleanup(events_path, offset_path)


def test_4_offset_not_advanced_on_send_failure(monkeypatch_post=None):
    events_path, offset_path = _temp_paths()
    original_post = splunk_forwarder.requests.post
    original_token = config.SPLUNK_HEC_TOKEN
    original_retries = config.SPLUNK_FORWARD_MAX_RETRIES
    try:
        config.SPLUNK_HEC_TOKEN = 'fake-token'
        config.SPLUNK_FORWARD_MAX_RETRIES = 1
        _write_events(events_path, [{'timestamp': '2026-08-03T10:00:00', 'type': 'FLOOD_DETECTED'}])

        splunk_forwarder.requests.post = lambda *a, **k: FakeResponse(status_code=503, text='Service Unavailable')

        sent = splunk_forwarder.run_once(events_file=events_path, offset_file=offset_path)
        offset_after = splunk_forwarder.load_offset(offset_path)
        ok = sent == 0 and offset_after == 0
        print(f"[Test 4] Offset not advanced when Splunk rejects the batch: {'OK' if ok else 'FAIL'}")
        return ok
    finally:
        splunk_forwarder.requests.post = original_post
        config.SPLUNK_HEC_TOKEN = original_token
        config.SPLUNK_FORWARD_MAX_RETRIES = original_retries
        _cleanup(events_path, offset_path)


def test_5_offset_advances_on_success_and_no_resend():
    events_path, offset_path = _temp_paths()
    original_post = splunk_forwarder.requests.post
    original_token = config.SPLUNK_HEC_TOKEN
    call_count = {'n': 0}
    try:
        config.SPLUNK_HEC_TOKEN = 'fake-token'
        _write_events(events_path, [{'timestamp': '2026-08-03T10:00:00', 'type': 'FLOOD_DETECTED'}])

        def fake_post(*a, **k):
            call_count['n'] += 1
            return FakeResponse(status_code=200, json_body={'code': 0})

        splunk_forwarder.requests.post = fake_post

        sent_first = splunk_forwarder.run_once(events_file=events_path, offset_file=offset_path)
        sent_second = splunk_forwarder.run_once(events_file=events_path, offset_file=offset_path)

        ok = sent_first == 1 and sent_second == 0 and call_count['n'] == 1
        print(f"[Test 5] Offset advances on success, no duplicate resend: {'OK' if ok else 'FAIL'}")
        return ok
    finally:
        splunk_forwarder.requests.post = original_post
        config.SPLUNK_HEC_TOKEN = original_token
        _cleanup(events_path, offset_path)


def test_6_no_token_configured_blocks_sending():
    events_path, offset_path = _temp_paths()
    original_token = config.SPLUNK_HEC_TOKEN
    try:
        config.SPLUNK_HEC_TOKEN = ''
        ok = splunk_forwarder.send_batch([{'timestamp': '2026-08-03T10:00:00', 'type': 'X'}]) is False
        print(f"[Test 6] Sending is skipped when no HEC token is configured: {'OK' if ok else 'FAIL'}")
        return ok
    finally:
        config.SPLUNK_HEC_TOKEN = original_token
        _cleanup(events_path, offset_path)


def test_7_hec_payload_shape():
    event = {'timestamp': '2026-08-03T10:00:00', 'type': 'SCAN_DETECTED', 'mitre_technique': 'T1046'}
    payload = splunk_forwarder.build_hec_payload(event)
    ok = (
        payload['event'] == event
        and payload['source'] == config.SPLUNK_HEC_SOURCE
        and payload['sourcetype'] == config.SPLUNK_HEC_SOURCETYPE
        and isinstance(payload['time'], float)
    )
    print(f"[Test 7] HEC payload has the expected shape: {'OK' if ok else 'FAIL'}")
    return ok


def run_all_tests():
    print("\n\n")
    print("#" * 60)
    print("# SPLUNK FORWARDER - TEST SUITE")
    print("#" * 60 + "\n")

    results = {
        "Test 1: Read new events (basic)": test_1_read_new_events_basic(),
        "Test 2: Malformed line skipped": test_2_malformed_line_is_skipped_but_offset_advances(),
        "Test 3: Incomplete trailing line not consumed": test_3_incomplete_trailing_line_not_consumed(),
        "Test 4: Offset not advanced on failure": test_4_offset_not_advanced_on_send_failure(),
        "Test 5: Offset advances on success, no resend": test_5_offset_advances_on_success_and_no_resend(),
        "Test 6: No token blocks sending": test_6_no_token_configured_blocks_sending(),
        "Test 7: HEC payload shape": test_7_hec_payload_shape(),
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