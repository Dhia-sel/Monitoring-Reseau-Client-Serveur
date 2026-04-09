import socket
import threading
import time
import csv
from datetime import datetime

HOST = '127.0.0.1'
PORT = 5051
ACTIVE_WINDOW = 30  
STATS_INTERVAL = 10
CSV_FILE = 'stats_export.csv'
CPU_ALERT_THRESHOLD = 85.0
ERROR_ALERT_THRESHOLD = 5
ERROR_ALERT_WINDOW = 10
ERROR_ALERT_COOLDOWN = 10


agents_lock = threading.Lock()
agents = {}  
metrics_lock = threading.Lock()
total_reports = 0
error_timestamps = []
last_error_alert_time = 0.0
alerts_lock = threading.Lock()
alerts = []
HEALTH_STATUSES = {'OK', 'DEGRADED', 'CRITICAL'}


def record_alert(alert_type, message, agent_id=None):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    payload = {
        'timestamp': timestamp,
        'type': alert_type,
        'agent_id': agent_id,
        'message': message,
    }
    with alerts_lock:
        alerts.append(payload)

    if agent_id:
        print(f"[ALERT][{alert_type}] {timestamp} | agent={agent_id} | {message}")
    else:
        print(f"[ALERT][{alert_type}] {timestamp} | {message}")


def get_recent_alerts(limit=20):
    with alerts_lock:
        return list(alerts[-limit:])


def reset_state_for_tests():
    global total_reports, last_error_alert_time
    with agents_lock:
        agents.clear()
    with metrics_lock:
        total_reports = 0
        error_timestamps.clear()
        last_error_alert_time = 0.0
    with alerts_lock:
        alerts.clear()


def register_error_response():
    global last_error_alert_time
    now = time.time()
    should_alert = False

    with metrics_lock:
        error_timestamps.append(now)
        while error_timestamps and (now - error_timestamps[0]) > ERROR_ALERT_WINDOW:
            error_timestamps.pop(0)

        if len(error_timestamps) >= ERROR_ALERT_THRESHOLD and (now - last_error_alert_time) >= ERROR_ALERT_COOLDOWN:
            last_error_alert_time = now
            should_alert = True

    if should_alert:
        record_alert(
            'ERROR_STORM',
            f"Too many ERROR responses: {len(error_timestamps)} in the last {ERROR_ALERT_WINDOW}s",
        )


def check_inactive_agents_once(now=None):
    if now is None:
        now = time.time()

    removed_agents = []
    with agents_lock:
        for agent_id, info in list(agents.items()):
            if (now - info['last_report_time']) >= ACTIVE_WINDOW:
                removed_agents.append((agent_id, info['hostname']))
                del agents[agent_id]

    for agent_id, hostname in removed_agents:
        record_alert(
            'AGENT_INACTIVE',
            f"Agent inactive too long and removed: {hostname}",
            agent_id=agent_id,
        )
        print(f"[CLEANUP] Agent inactive removed: {agent_id} ({hostname})")

    return removed_agents


def write_csv_row(timestamp, num_active, avg_cpu, avg_ram):
    file_exists = False
    try:
        with open(CSV_FILE, 'r', encoding='utf-8'):
            file_exists = True
    except FileNotFoundError:
        file_exists = False

    with open(CSV_FILE, 'a', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        if not file_exists:
            writer.writerow(['timestamp', 'active_agents', 'avg_cpu_pct', 'avg_ram_mb', 'total_reports'])
        with metrics_lock:
            writer.writerow([timestamp, num_active, f"{avg_cpu:.2f}", f"{avg_ram:.2f}", total_reports])


def validate_report(cpu_pct, ram_mb):
    return 0 <= cpu_pct <= 100 and ram_mb >= 0


def validate_health(status, uptime_s, error_count):
    return status in HEALTH_STATUSES and uptime_s >= 0 and error_count >= 0


def process_message(message, addr, protocol='TCP'):
    global total_reports

    message = message.strip()
    if not message:
        register_error_response()
        return 'ERROR', False

    print(f"[{protocol} {addr}] Received: {message}")
    tokens = message.split()

    if message.startswith('HELLO'):
        if len(tokens) < 3:
            print(f"[{protocol} {addr}] ERROR: Malformed HELLO message")
            register_error_response()
            return 'ERROR', False

        agent_id = tokens[1]
        hostname = tokens[2]

        with agents_lock:
            agents[agent_id] = {
                'hostname': hostname,
                'last_report_time': time.time(),
                'cpu_pct': 0.0,
                'ram_mb': 0.0,
                'protocol': protocol,
                'addr': str(addr),
                'cpu_alert_active': False,
                'health': {
                    'timestamp': 0,
                    'status': 'OK',
                    'uptime_s': 0.0,
                    'error_count': 0,
                    'last_health_time': 0.0,
                },
            }

        print(f"[{protocol} {addr}] Agent registered: {agent_id} ({hostname})")
        return 'OK', False

    if message.startswith('REPORT'):
        if len(tokens) < 5:
            print(f"[{protocol} {addr}] ERROR: Malformed REPORT message")
            register_error_response()
            return 'ERROR', False

        try:
            agent_id = tokens[1]
            _timestamp = int(tokens[2])
            cpu_pct = float(tokens[3])
            ram_mb = float(tokens[4])

            if not validate_report(cpu_pct, ram_mb):
                print(f"[{protocol} {addr}] ERROR: Invalid metric values")
                register_error_response()
                return 'ERROR', False

            with agents_lock:
                if agent_id in agents:
                    was_above_threshold = agents[agent_id].get('cpu_alert_active', False)
                    agents[agent_id]['last_report_time'] = time.time()
                    agents[agent_id]['cpu_pct'] = cpu_pct
                    agents[agent_id]['ram_mb'] = ram_mb
                    agents[agent_id]['protocol'] = protocol
                    agents[agent_id]['addr'] = str(addr)

                    is_above_threshold = cpu_pct > CPU_ALERT_THRESHOLD
                    if is_above_threshold and not was_above_threshold:
                        agents[agent_id]['cpu_alert_active'] = True
                        record_alert(
                            'CPU_HIGH',
                            f"CPU above threshold: {cpu_pct:.1f}% > {CPU_ALERT_THRESHOLD:.1f}%",
                            agent_id=agent_id,
                        )
                    elif not is_above_threshold and was_above_threshold:
                        agents[agent_id]['cpu_alert_active'] = False
                else:
                    print(f"[{protocol} {addr}] WARNING: Report from unregistered agent {agent_id}")
                    register_error_response()
                    return 'ERROR', False

            with metrics_lock:
                total_reports += 1

            print(f"[{protocol} {addr}] Report recorded: {agent_id} CPU={cpu_pct}% RAM={ram_mb}MB")
            return 'OK', False

        except ValueError:
            print(f"[{protocol} {addr}] ERROR: Invalid metric format")
            register_error_response()
            return 'ERROR', False

    if message.startswith('HEALTH'):
        if len(tokens) < 6:
            print(f"[{protocol} {addr}] ERROR: Malformed HEALTH message")
            register_error_response()
            return 'ERROR', False

        try:
            agent_id = tokens[1]
            health_timestamp = int(tokens[2])
            status = tokens[3]
            uptime_s = float(tokens[4])
            error_count = int(tokens[5])

            if not validate_health(status, uptime_s, error_count):
                print(f"[{protocol} {addr}] ERROR: Invalid HEALTH values")
                register_error_response()
                return 'ERROR', False

            with agents_lock:
                if agent_id not in agents:
                    print(f"[{protocol} {addr}] WARNING: HEALTH from unregistered agent {agent_id}")
                    register_error_response()
                    return 'ERROR', False

                agents[agent_id]['health'] = {
                    'timestamp': health_timestamp,
                    'status': status,
                    'uptime_s': uptime_s,
                    'error_count': error_count,
                    'last_health_time': time.time(),
                }

            print(
                f"[{protocol} {addr}] Health recorded: {agent_id} "
                f"status={status} uptime={uptime_s:.1f}s errors={error_count}"
            )
            return 'OK', False

        except ValueError:
            print(f"[{protocol} {addr}] ERROR: Invalid HEALTH format")
            register_error_response()
            return 'ERROR', False

    if message.startswith('BYE'):
        if len(tokens) < 2:
            print(f"[{protocol} {addr}] ERROR: Malformed BYE message")
            register_error_response()
            return 'ERROR', False

        agent_id = tokens[1]
        with agents_lock:
            if agent_id in agents:
                del agents[agent_id]

        print(f"[{protocol} {addr}] Agent unregistered: {agent_id}")
        return 'OK', protocol == 'TCP'

    print(f"[{protocol} {addr}] ERROR: Unknown command")
    register_error_response()
    return 'ERROR', False


def is_agent_active(agent_id):
    with agents_lock:
        if agent_id not in agents:
            return False
        last_report = agents[agent_id]['last_report_time']
        return (time.time() - last_report) < ACTIVE_WINDOW


def handle_client(conn, addr):
    try:
        buffer = ''
        while True:
            data = conn.recv(1024)
            if not data:
                break
            buffer += data.decode('utf-8')

            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                response, should_close = process_message(line, addr, protocol='TCP')
                conn.send((response + '\n').encode('utf-8'))
                if should_close:
                    return
    
    except Exception as e:
        print(f"[TCP {addr}] Exception: {e}")
    
    finally:
        conn.close()
        print(f"[TCP {addr}] Connection closed")


def udp_listener(udp_socket):
    """Handle UDP datagrams."""
    while True:
        try:
            data, addr = udp_socket.recvfrom(2048)
            message = data.decode('utf-8').strip()
            response, _ = process_message(message, addr, protocol='UDP')
            udp_socket.sendto((response + '\n').encode('utf-8'), addr)
        except Exception as e:
            print(f"[UDP] Listener exception: {e}")


def inactive_cleanup_thread():
    while True:
        time.sleep(5)
        check_inactive_agents_once()


def statistics_thread():
    while True:
        time.sleep(STATS_INTERVAL)
        
        with agents_lock:
            active_agents = dict(agents)
            num_active = len(active_agents)

            if num_active > 0:
                avg_cpu = sum(info['cpu_pct'] for info in active_agents.values()) / num_active
                avg_ram = sum(info['ram_mb'] for info in active_agents.values()) / num_active
            else:
                avg_cpu = 0.0
                avg_ram = 0.0
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n[{timestamp}] ===== STATISTICS =====")
        print(f"Active Agents: {num_active}")
        print(f"Average CPU: {avg_cpu:.2f}%")
        print(f"Average RAM: {avg_ram:.2f}MB")
        with metrics_lock:
            print(f"Total REPORT received: {total_reports}")
            print(f"Recent ERROR count ({ERROR_ALERT_WINDOW}s): {len(error_timestamps)}")
        recent_alerts = get_recent_alerts(limit=3)
        if recent_alerts:
            print("Recent Alerts:")
            for alert in recent_alerts:
                agent_label = f" [{alert['agent_id']}]" if alert['agent_id'] else ''
                print(f"  - {alert['timestamp']} {alert['type']}{agent_label}: {alert['message']}")
        if active_agents:
            for agent_id, info in active_agents.items():
                health = info.get('health', {})
                health_status = health.get('status', 'N/A')
                health_errors = health.get('error_count', 0)
                print(
                    f"  {agent_id} ({info['hostname']}) [{info['protocol']}]: "
                    f"CPU={info['cpu_pct']:.1f}% RAM={info['ram_mb']:.0f}MB "
                    f"HEALTH={health_status} ERR={health_errors}"
                )
        print("=" * 23 + "\n")

        try:
            write_csv_row(timestamp, num_active, avg_cpu, avg_ram)
        except Exception as e:
            print(f"[CSV] Export error: {e}")


def main():
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp_socket.bind((HOST, PORT))
    tcp_socket.listen(10)

    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_socket.bind((HOST, PORT))

    print(f"Server listening on {HOST}:{PORT} (TCP + UDP)")
    print(f"Active window: {ACTIVE_WINDOW} seconds")
    print(f"CSV export file: {CSV_FILE}\n")

    threading.Thread(target=statistics_thread, daemon=True).start()
    threading.Thread(target=inactive_cleanup_thread, daemon=True).start()
    threading.Thread(target=udp_listener, args=(udp_socket,), daemon=True).start()

    try:
        while True:
            conn, addr = tcp_socket.accept()
            print(f"[TCP] New connection from {addr}")

            client_thread = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            client_thread.start()

    except KeyboardInterrupt:
        print("\nServer shutting down...")

    finally:
        tcp_socket.close()
        udp_socket.close()


if __name__ == '__main__':
    main()
