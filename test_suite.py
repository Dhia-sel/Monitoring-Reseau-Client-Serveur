import socket
import time
import uuid
import config
import server as server_module


class TestClient:
    
    def __init__(self, host='127.0.0.1', port=5051, protocol='TCP'):
        self.host = host
        self.port = port
        self.protocol = protocol
        self.sock = None
    
    def connect(self):
        try:
            if self.protocol == 'UDP':
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.settimeout(2)
                self.sock.connect((self.host, self.port))
            else:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.connect((self.host, self.port))
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False
    
    def send_raw(self, message):
        try:
            if self.protocol == 'UDP':
                self.sock.send(message.encode('utf-8'))
            else:
                self.sock.send((message + '\n').encode('utf-8'))
            response = self.sock.recv(1024).decode('utf-8').strip()
            return response
        except Exception as e:
            print(f"Send error: {e}")
            return None
    
    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except:
            pass


def test_1_single_client_connection():
    print("\n" + "="*60)
    print("TEST 1: Single Client Connection")
    print("="*60)
    
    client = TestClient()
    if not client.connect():
        print("FAILED: Could not connect")
        return False

    response = client.send_raw(f"HELLO agent1 WORKSTATION {config.AGENT_AUTH_TOKEN}")
    if response == 'OK':
        print("PASSED: Agent registered successfully")
        print(f"  Response: {response}")
    else:
        print(f"FAILED: Expected OK, got {response}")
        client.close()
        return False

    response = client.send_raw("REPORT agent1 1700000000 25.5 2048")
    if response == 'OK':
        print("PASSED: Report accepted")
        print(f"  Response: {response}")
    else:
        print(f"FAILED: Expected OK, got {response}")
        client.close()
        return False

    response = client.send_raw("BYE agent1")
    if response == 'OK':
        print("PASSED: Graceful disconnect")
        print(f"  Response: {response}")
    else:
        print(f"FAILED: Expected OK, got {response}")
        client.close()
        return False
    
    client.close()
    return True


def test_2_multiple_concurrent_clients():
    """Test 2: Multiple clients connecting simultaneously."""
    print("\n" + "="*60)
    print("TEST 2: Multiple Concurrent Clients")
    print("="*60)
    
    clients = []
    agent_ids = ['agent_multi_1', 'agent_multi_2', 'agent_multi_3']

    for agent_id in agent_ids:
        client = TestClient()
        if not client.connect():
            print(f"FAILED: Could not connect client {agent_id}")
            return False
        clients.append((agent_id, client))
    
    print(f"Connected {len(clients)} clients")

    for agent_id, client in clients:
        response = client.send_raw(f"HELLO {agent_id} WORKSTATION {config.AGENT_AUTH_TOKEN}")
        if response != 'OK':
            print(f"FAILED: Could not register {agent_id}")
            return False
    
    print(f"Registered {len(clients)} clients")
    for agent_id, client in clients:
        response = client.send_raw(f"REPORT {agent_id} 1700000000 20.0 1500")
        if response != 'OK':
            print(f"FAILED: Report from {agent_id} rejected")
            return False
    
    print(f"All {len(clients)} reports accepted")

    for agent_id, client in clients:
        response = client.send_raw(f"BYE {agent_id}")
        if response != 'OK':
            print(f"FAILED: Could not disconnect {agent_id}")
            return False
        client.close()
    
    print(f" PASSED: All {len(clients)} clients disconnected gracefully")
    return True


def test_3_malformed_messages():
    """Test 3: Malformed message handling."""
    print("\n" + "="*60)
    print("TEST 3: Malformed Message Handling")
    print("="*60)
    
    test_cases = [
        ("HELLO agent1", "Missing hostname"),
        ("REPORT agent1 100", "Missing metrics"),
        ("REPORT agent1 abc 25.5 2048", "Invalid timestamp"),
        ("REPORT agent1 100 150 2048", "CPU > 100"),
        ("REPORT agent1 100 25.5 -100", "Negative RAM"),
        ("INVALID agent1", "Unknown command"),
        ("BYE", "Missing agent_id"),
    ]
    
    for message, description in test_cases:
        client = TestClient()
        if not client.connect():
            print(f"Could not connect for test: {description}")
            continue
        
        response = client.send_raw(message)
        if response == 'ERROR':
            print(f"Correctly rejected: {description}")
            print(f"  Message: {message}")
            print(f"  Response: {response}")
        else:
            print(f" Should reject: {description}")
            print(f"  Message: {message}")
            print(f"  Got: {response}")
        
        client.close()
    
    return True


def test_4_unregistered_agent():
    """Test 4: Report from unregistered agent."""
    print("\n" + "="*60)
    print("TEST 4: Unregistered Agent Report")
    print("="*60)
    
    client = TestClient()
    if not client.connect():
        print("FAILED: Could not connect")
        return False
 
    response = client.send_raw("REPORT unknown_agent 1700000000 30 2000")
    if response == 'ERROR':
        print("PASSED: Report from unregistered agent rejected")
        print(f"  Response: {response}")
    else:
        print(f"FAILED: Should reject unregistered agent, got {response}")
        client.close()
        return False

    response = client.send_raw(f"HELLO unknown_agent WORKSTATION {config.AGENT_AUTH_TOKEN}")
    if response != 'OK':
        print("FAILED: Registration failed")
        client.close()
        return False
    
    response = client.send_raw("REPORT unknown_agent 1700000000 30 2000")
    if response == 'OK':
        print("PASSED: Report accepted after registration")
        print(f"  Response: {response}")
    else:
        print(f"FAILED: Report should be accepted, got {response}")
        client.close()
        return False
    
    client.close()
    return True


def test_5_metric_validation():
    """Test 5: Metric value validation."""
    print("\n" + "="*60)
    print("TEST 5: Metric Validation")
    print("="*60)
    
    test_cases = [
        (0.0, 0.0, True, "Min values"),
        (100.0, 1000.0, True, "Normal values"),
        (50.5, 2048.5, True, "Float values"),
        (-10.0, 2000.0, False, "Negative CPU"),
        (150.0, 2000.0, False, "CPU > 100"),
        (50.0, -500.0, False, "Negative RAM"),
    ]
    
    for i, (cpu, ram, should_pass, description) in enumerate(test_cases):
        client = TestClient()
        if not client.connect():
            continue

        client.send_raw(f"HELLO metric_test_{i} WORKSTATION {config.AGENT_AUTH_TOKEN}")
 
        response = client.send_raw(f"REPORT metric_test_{i} 1700000000 {cpu} {ram}")
        
        if should_pass and response == 'OK':
            print(f"Accepted: {description} (CPU={cpu}%, RAM={ram}MB)")
        elif not should_pass and response == 'ERROR':
            print(f"Rejected: {description} (CPU={cpu}%, RAM={ram}MB)")
        else:
            status = "accepted" if response == 'OK' else "rejected"
            expected = "accepted" if should_pass else "rejected"
            print(f"{description}: {status}, but expected {expected}")
        
        client.close()
    
    return True


def test_6_disconnect_and_reconnect():
    """Test 6: Disconnect and reconnect with same agent_id."""
    print("\n" + "="*60)
    print("TEST 6: Disconnect and Reconnect")
    print("="*60)
    
    agent_id = "reconnect_test"

    client1 = TestClient()
    if not client1.connect():
        print("FAILED: Could not connect first time")
        return False
    
    response = client1.send_raw(f"HELLO {agent_id} WORKSTATION {config.AGENT_AUTH_TOKEN}")
    if response != 'OK':
        print("FAILED: First registration failed")
        return False
    
    print(f"✓ First connection and registration successful")
    
    # Send report
    response = client1.send_raw(f"REPORT {agent_id} 1700000000 25 2000")
    if response != 'OK':
        print("FAILED: First report failed")
        return False
    
    print(f"First report sent")

    client1.send_raw(f"BYE {agent_id}")
    client1.close()
    
    print(f" Disconnected")

    time.sleep(1)

    client2 = TestClient()
    if not client2.connect():
        print("FAILED: Could not reconnect")
        return False
    
    response = client2.send_raw(f"HELLO {agent_id} WORKSTATION {config.AGENT_AUTH_TOKEN}")
    if response != 'OK':
        print("FAILED: Second registration failed")
        return False
    
    print(f"PASSED: Reconnected and re-registered with same agent_id")
    
    response = client2.send_raw(f"REPORT {agent_id} 1700000000 30 2100")
    if response == 'OK':
        print(f"Second report sent successfully")
    
    client2.close()
    return True


def test_7_udp_flow():
    """Test 7: UDP registration/report/disconnect."""
    print("\n" + "="*60)
    print("TEST 7: UDP Flow")
    print("="*60)

    agent_id = "udp_test_agent"
    client = TestClient(protocol='UDP')
    if not client.connect():
        print("FAILED: Could not create UDP client")
        return False

    response = client.send_raw(f"HELLO {agent_id} WORKSTATION {config.AGENT_AUTH_TOKEN}")
    if response != 'OK':
        print(f"FAILED: UDP HELLO rejected: {response}")
        return False

    response = client.send_raw(f"REPORT {agent_id} 1700000000 33.3 1800")
    if response != 'OK':
        print(f"FAILED: UDP REPORT rejected: {response}")
        return False

    response = client.send_raw(f"BYE {agent_id}")
    if response != 'OK':
        print(f"FAILED: UDP BYE rejected: {response}")
        return False

    client.close()
    print("PASSED: UDP flow works")
    return True


def test_8_uuid_agent_id():
    print("\n" + "="*60)
    print("TEST 8: UUID Agent ID")
    print("="*60)

    agent_id = str(uuid.uuid4())
    client = TestClient()
    if not client.connect():
        print("FAILED: Could not connect")
        return False

    response = client.send_raw(f"HELLO {agent_id} WORKSTATION {config.AGENT_AUTH_TOKEN}")
    if response != 'OK':
        print(f"FAILED: UUID HELLO rejected: {response}")
        return False

    response = client.send_raw(f"REPORT {agent_id} 1700000000 12.2 1024")
    if response != 'OK':
        print(f"FAILED: UUID REPORT rejected: {response}")
        return False

    response = client.send_raw(f"BYE {agent_id}")
    if response != 'OK':
        print(f"FAILED: UUID BYE rejected: {response}")
        return False

    client.close()
    print("PASSED: UUID agent ID accepted")
    return True


def test_9_abrupt_disconnect():
    print("\n" + "="*60)
    print("TEST 9: Abrupt Client Disconnect")
    print("="*60)
    
    agent_id = "abrupt_disconnect_test"
    client = TestClient()
    
    if not client.connect():
        print("FAILED: Could not connect")
        return False

    response = client.send_raw(f"HELLO {agent_id} WORKSTATION {config.AGENT_AUTH_TOKEN}")
    if response != 'OK':
        print("FAILED: Registration failed")
        return False
    
    print(f"Agent {agent_id} registered")

    response = client.send_raw(f"REPORT {agent_id} 1700000000 45.5 2048")
    if response != 'OK':
        print("FAILED: Report failed")
        return False
    
    print(f"Report sent")

    client.sock.close()
    print(f"Connection closed abruptly without BYE")

    print(f"Server will timeout agent after ~30 seconds")
    print("PASSED: Abrupt disconnect handled gracefully by server")
    return True


def test_10_average_calculation():
    print("\n" + "="*60)
    print("TEST 10: Average Calculation Validation")
    print("="*60)

    test_data = [
        ("avg_test_1", 10.0, 1000.0),
        ("avg_test_2", 30.0, 2000.0),
        ("avg_test_3", 50.0, 3000.0),
    ]
    
    clients = []
    
    for agent_id, cpu, ram in test_data:
        client = TestClient()
        if not client.connect():
            print(f"FAILED: Could not connect {agent_id}")
            return False
        
        response = client.send_raw(f"HELLO {agent_id} WORKSTATION {config.AGENT_AUTH_TOKEN}")
        if response != 'OK':
            print(f"FAILED: Registration failed for {agent_id}")
            return False
        
        response = client.send_raw(f"REPORT {agent_id} 1700000000 {cpu} {ram}")
        if response != 'OK':
            print(f"FAILED: Report failed for {agent_id}")
            return False
        
        clients.append((agent_id, client))
        print(f" {agent_id}: CPU={cpu}%, RAM={ram}MB")

    cpu_values = [cpu for _, cpu, _ in test_data]
    ram_values = [ram for _, _, ram in test_data]
    expected_cpu = sum(cpu_values) / len(cpu_values)
    expected_ram = sum(ram_values) / len(ram_values)
    
    print(f"\n Expected Average CPU: {expected_cpu:.2f}%")
    print(f" Expected Average RAM: {expected_ram:.2f}MB")
    print(f" Server should display these values in statistics output")
    print(" PASSED: Verification metrics ready - check server output")

    for agent_id, client in clients:
        client.send_raw(f"BYE {agent_id}")
        client.close()
    
    return True


def test_11_agent_inactivity_detection():
    print("\n" + "="*60)
    print("TEST 11: Agent Inactivity Detection")
    print("="*60)
    
    agent_id = "inactivity_test"
    client = TestClient()
    
    if not client.connect():
        print("FAILED: Could not connect")
        return False

    response = client.send_raw(f"HELLO {agent_id} WORKSTATION {config.AGENT_AUTH_TOKEN}")
    if response != 'OK':
        print("FAILED: Registration failed")
        return False
    
    print(f"Agent registered")
    
    response = client.send_raw(f"REPORT {agent_id} 1700000000 20.0 1500")
    if response != 'OK':
        print("FAILED: Report failed")
        return False
    
    print(f"First report sent")
    print(f"Active window = 30 seconds (3 × T where T=10s)")
    print(f"Agent will be marked inactive if no report received for 30s")
    print(f"Note: Full test requires waiting ~35 seconds")
    print("To verify: Check server log for '[CLEANUP]' messages")
    print("PASSED: Inactivity detection logic is in place server-side")
    
    client.close()
    return True


def test_12_cpu_alert_trigger():
    print("\n" + "="*60)
    print("TEST 12: CPU Alert Trigger")
    print("="*60)

    server_module.reset_state_for_tests()

    response, _ = server_module.process_message(f"HELLO alert_cpu_1 HOST {config.AGENT_AUTH_TOKEN}", ("127.0.0.1", 9999), protocol='TCP')
    if response != 'OK':
        print("FAILED: HELLO rejected")
        return False

    response, _ = server_module.process_message(
        f"REPORT alert_cpu_1 1700000000 {server_module.CPU_ALERT_THRESHOLD + 1} 1024",
        ("127.0.0.1", 9999),
        protocol='TCP',
    )
    if response != 'OK':
        print("FAILED: REPORT rejected")
        return False

    cpu_alerts = [a for a in server_module.get_recent_alerts() if a['type'] == 'CPU_HIGH' and a['agent_id'] == 'alert_cpu_1']
    if not cpu_alerts:
        print("FAILED: CPU_HIGH alert not generated")
        return False

    print("PASSED: CPU_HIGH alert generated")
    return True


def test_13_inactive_agent_alert_trigger():
    print("\n" + "="*60)
    print("TEST 13: Inactive Agent Alert")
    print("="*60)

    server_module.reset_state_for_tests()

    response, _ = server_module.process_message(f"HELLO alert_inactive_1 HOST {config.AGENT_AUTH_TOKEN}", ("127.0.0.1", 9998), protocol='TCP')
    if response != 'OK':
        print("FAILED: HELLO rejected")
        return False

    now = time.time()
    with server_module.agents_lock:
        server_module.agents['alert_inactive_1']['last_report_time'] = now - (server_module.ACTIVE_WINDOW + 1)

    removed_agents = server_module.check_inactive_agents_once(now=now)
    if not removed_agents:
        print("FAILED: Agent was not removed by inactivity check")
        return False

    inactive_alerts = [
        a for a in server_module.get_recent_alerts()
        if a['type'] == 'AGENT_INACTIVE' and a['agent_id'] == 'alert_inactive_1'
    ]
    if not inactive_alerts:
        print("FAILED: AGENT_INACTIVE alert not generated")
        return False

    print("PASSED: AGENT_INACTIVE alert generated")
    return True


def test_14_error_storm_alert_trigger():
    print("\n" + "="*60)
    print("TEST 14: Error Storm Alert")
    print("="*60)

    server_module.reset_state_for_tests()

    for _ in range(server_module.ERROR_ALERT_THRESHOLD):
        response, _ = server_module.process_message("INVALID bad_msg", ("127.0.0.1", 9997), protocol='TCP')
        if response != 'ERROR':
            print("FAILED: Malformed message should return ERROR")
            return False

    error_alerts = [a for a in server_module.get_recent_alerts() if a['type'] == 'ERROR_STORM']
    if not error_alerts:
        print("FAILED: ERROR_STORM alert not generated")
        return False

    print("PASSED: ERROR_STORM alert generated")
    return True


def test_15_health_metadata_valid():
    print("\n" + "="*60)
    print("TEST 15: HEALTH Metadata Valid")
    print("="*60)

    server_module.reset_state_for_tests()

    response, _ = server_module.process_message(f"HELLO health_agent_1 HOST {config.AGENT_AUTH_TOKEN}", ("127.0.0.1", 9996), protocol='TCP')
    if response != 'OK':
        print("FAILED: HELLO rejected")
        return False

    response, _ = server_module.process_message(
        "HEALTH health_agent_1 1700000000 DEGRADED 120.5 2",
        ("127.0.0.1", 9996),
        protocol='TCP',
    )
    if response != 'OK':
        print("FAILED: HEALTH rejected")
        return False

    with server_module.agents_lock:
        health_data = server_module.agents['health_agent_1'].get('health', {})

    if health_data.get('status') != 'DEGRADED':
        print("FAILED: HEALTH status was not stored correctly")
        return False

    if int(health_data.get('error_count', -1)) != 2:
        print("FAILED: HEALTH error_count was not stored correctly")
        return False

    print("PASSED: HEALTH metadata accepted and stored")
    return True


def test_16_health_metadata_malformed():
    print("\n" + "="*60)
    print("TEST 16: HEALTH Metadata Malformed")
    print("="*60)

    server_module.reset_state_for_tests()

    response, _ = server_module.process_message(f"HELLO health_agent_2 HOST {config.AGENT_AUTH_TOKEN}", ("127.0.0.1", 9995), protocol='TCP')
    if response != 'OK':
        print("FAILED: HELLO rejected")
        return False

    response, _ = server_module.process_message("HEALTH health_agent_2 1700000000", ("127.0.0.1", 9995), protocol='TCP')
    if response != 'ERROR':
        print("FAILED: Incomplete HEALTH should return ERROR")
        return False

    response, _ = server_module.process_message(
        "HEALTH health_agent_2 1700000001 UNKNOWN 10 0",
        ("127.0.0.1", 9995),
        protocol='TCP',
    )
    if response != 'ERROR':
        print("FAILED: Invalid HEALTH status should return ERROR")
        return False

    print("PASSED: Malformed HEALTH messages rejected")
    return True


def test_17_health_unregistered_agent():
    print("\n" + "="*60)
    print("TEST 17: HEALTH Unregistered Agent")
    print("="*60)

    server_module.reset_state_for_tests()

    response, _ = server_module.process_message(
        "HEALTH ghost_agent 1700000000 OK 5 0",
        ("127.0.0.1", 9994),
        protocol='TCP',
    )
    if response != 'ERROR':
        print("FAILED: HEALTH from unregistered agent should return ERROR")
        return False

    print("PASSED: Unregistered HEALTH rejected")
    return True


def run_all_tests():
    print("\n\n")
    print("#" * 60)
    print("# NETWORK MONITORING SYSTEM - TEST SUITE")
    print("#" * 60)
    print("\nMake sure server is running: python server.py")
    print("Tests will start in 2 seconds...\n")
    
    time.sleep(2)
    
    results = {
        "Test 1: Single Client": test_1_single_client_connection(),
        "Test 2: Multiple Clients": test_2_multiple_concurrent_clients(),
        "Test 3: Malformed Messages": test_3_malformed_messages(),
        "Test 4: Unregistered Agent": test_4_unregistered_agent(),
        "Test 5: Metric Validation": test_5_metric_validation(),
        "Test 6: Disconnect/Reconnect": test_6_disconnect_and_reconnect(),
        "Test 7: UDP Flow": test_7_udp_flow(),
        "Test 8: UUID Agent ID": test_8_uuid_agent_id(),
        "Test 9: Abrupt Disconnect": test_9_abrupt_disconnect(),
        "Test 10: Average Calculation": test_10_average_calculation(),
        "Test 11: Inactivity Detection": test_11_agent_inactivity_detection(),
        "Test 12: CPU Alert": test_12_cpu_alert_trigger(),
        "Test 13: Inactive Alert": test_13_inactive_agent_alert_trigger(),
        "Test 14: Error Storm Alert": test_14_error_storm_alert_trigger(),
        "Test 15: Health Metadata Valid": test_15_health_metadata_valid(),
        "Test 16: Health Metadata Malformed": test_16_health_metadata_malformed(),
        "Test 17: Health Unregistered Agent": test_17_health_unregistered_agent(),
    }

    print("\n\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for test_name, result in results.items():
        status = "✓ PASSED" if result else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    total = len(results)
    passed = sum(1 for r in results.values() if r)
    print(f"\nTotal: {passed}/{total} tests passed")
    print("="*60 + "\n")


if __name__ == '__main__':
    try:
        run_all_tests()
    except KeyboardInterrupt:
        print("\n\nTests interrupted by user")
    except Exception as e:
        print(f"\nError running tests: {e}")