import socket
import threading
import time
import uuid
import os
import re
import platform
import subprocess
import ctypes
from datetime import datetime

# Server configuration
HOST = '127.0.0.1'
PORT = 5051
REPORT_INTERVAL = 10  # Send report every 10 seconds
SEND_HEALTH_METADATA = True


def get_system_metrics():
    try:
        cpu_pct = get_cpu_usage_pct()
        ram_mb = get_used_memory_mb()
        return cpu_pct, ram_mb
    except Exception as e:
        print(f"Error collecting metrics: {e}")
        return 0.0, 0.0


def get_cpu_usage_pct():
    system_name = platform.system()

    if system_name == 'Windows':
        return get_cpu_windows()

    # Unix fallback: convert 1-minute load average to a rough CPU percentage.
    if hasattr(os, 'getloadavg'):
        load_1m = os.getloadavg()[0]
        cpu_count = os.cpu_count() or 1
        return max(0.0, min(100.0, (load_1m / cpu_count) * 100.0))

    return 0.0


def get_cpu_windows():
    try:
        result = subprocess.run(
            ['typeperf', r'\Processor(_Total)\% Processor Time', '-sc', '1'],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for line in reversed(result.stdout.splitlines()):
            matches = re.findall(r'-?\d+(?:[\.,]\d+)?', line)
            if matches:
                value = float(matches[-1].replace(',', '.'))
                return max(0.0, min(100.0, value))
    except Exception:
        pass
    return 0.0


def get_used_memory_mb():
    system_name = platform.system()
    if system_name == 'Windows':
        return get_used_memory_mb_windows()
    if system_name == 'Linux':
        return get_used_memory_mb_linux()
    if system_name == 'Darwin':
        return get_used_memory_mb_darwin()
    return 0.0


def get_used_memory_mb_windows():

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ('dwLength', ctypes.c_ulong),
            ('dwMemoryLoad', ctypes.c_ulong),
            ('ullTotalPhys', ctypes.c_ulonglong),
            ('ullAvailPhys', ctypes.c_ulonglong),
            ('ullTotalPageFile', ctypes.c_ulonglong),
            ('ullAvailPageFile', ctypes.c_ulonglong),
            ('ullTotalVirtual', ctypes.c_ulonglong),
            ('ullAvailVirtual', ctypes.c_ulonglong),
            ('sullAvailExtendedVirtual', ctypes.c_ulonglong),
        ]

    mem_status = MEMORYSTATUSEX()
    mem_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem_status)):
        used = mem_status.ullTotalPhys - mem_status.ullAvailPhys
        return used / (1024 * 1024)
    return 0.0


def get_used_memory_mb_linux():
    total_kb = None
    available_kb = None
    with open('/proc/meminfo', 'r', encoding='utf-8') as meminfo:
        for line in meminfo:
            if line.startswith('MemTotal:'):
                total_kb = int(line.split()[1])
            elif line.startswith('MemAvailable:'):
                available_kb = int(line.split()[1])
            if total_kb is not None and available_kb is not None:
                break

    if total_kb is None or available_kb is None:
        return 0.0
    return (total_kb - available_kb) / 1024.0


def get_used_memory_mb_darwin():
    try:
        pagesize_result = subprocess.run(
            ['sysctl', '-n', 'hw.pagesize'],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        page_size = int(pagesize_result.stdout.strip())

        vm_result = subprocess.run(
            ['vm_stat'],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        active = inactive = wired = compressed = 0
        for line in vm_result.stdout.splitlines():
            value_match = re.search(r'(\d+)\.$', line.strip())
            if not value_match:
                continue
            pages = int(value_match.group(1))
            if 'Pages active' in line:
                active = pages
            elif 'Pages inactive' in line:
                inactive = pages
            elif 'Pages wired down' in line:
                wired = pages
            elif 'Pages occupied by compressor' in line:
                compressed = pages

        used_bytes = (active + inactive + wired + compressed) * page_size
        return used_bytes / (1024 * 1024)
    except Exception:
        return 0.0


def send_message_tcp(sock, message):
    try:
        sock.send((message + '\n').encode('utf-8'))
        response = sock.recv(1024).decode('utf-8').strip()
        return response
    except Exception as e:
        print(f"Error communicating with server: {e}")
        return None


def send_message_udp(sock, message):
    try:
        sock.send(message.encode('utf-8'))
        response = sock.recv(1024).decode('utf-8').strip()
        return response
    except Exception as e:
        print(f"Error communicating with server (UDP): {e}")
        return None


def compute_health_status(cpu_pct, local_error_count):
    if cpu_pct >= 90.0 or local_error_count >= 3:
        return 'CRITICAL'
    if cpu_pct >= 75.0 or local_error_count >= 1:
        return 'DEGRADED'
    return 'OK'


def report_thread(sock, agent_id, protocol='TCP'):
    start_time = time.time()
    local_error_count = 0
    health_enabled = SEND_HEALTH_METADATA

    while True:
        try:
            time.sleep(REPORT_INTERVAL)
            
            cpu_pct, ram_mb = get_system_metrics()
            timestamp = int(time.time())
            
            message = f"REPORT {agent_id} {timestamp} {cpu_pct:.1f} {ram_mb:.0f}"
            if protocol == 'UDP':
                response = send_message_udp(sock, message)
            else:
                response = send_message_tcp(sock, message)
            
            if response == 'OK':
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Report sent: CPU={cpu_pct:.1f}% RAM={ram_mb:.0f}MB")
            else:
                local_error_count += 1
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Report rejected: {response}")

            if health_enabled:
                uptime_s = time.time() - start_time
                status = compute_health_status(cpu_pct, local_error_count)
                health_msg = f"HEALTH {agent_id} {timestamp} {status} {uptime_s:.1f} {local_error_count}"

                if protocol == 'UDP':
                    health_response = send_message_udp(sock, health_msg)
                else:
                    health_response = send_message_tcp(sock, health_msg)

                if health_response == 'OK':
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] "
                        f"Health sent: status={status} uptime={uptime_s:.0f}s errors={local_error_count}"
                    )
                elif health_response == 'ERROR':
                    health_enabled = False
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] "
                        "Server rejected HEALTH extension; continuing with HELLO/REPORT/BYE only"
                    )
                else:
                    local_error_count += 1
        
        except Exception as e:
            print(f"Error in report thread: {e}")
            break


def run_attack_mode(sock, agent_id, protocol, burst_count):
    print(f"\n[ATTACK] Sending {burst_count} REPORT messages using {protocol}...")
    start = time.time()
    ok_count = 0

    for _ in range(burst_count):
        cpu_pct, ram_mb = get_system_metrics()
        timestamp = int(time.time())
        message = f"REPORT {agent_id} {timestamp} {cpu_pct:.1f} {ram_mb:.0f}"

        if protocol == 'UDP':
            response = send_message_udp(sock, message)
        else:
            response = send_message_tcp(sock, message)

        if response == 'OK':
            ok_count += 1

    elapsed = time.time() - start
    print(f"[ATTACK] Completed in {elapsed:.2f}s - accepted: {ok_count}/{burst_count}")


def main():
    """Main client function."""
    # Get agent configuration
    generated_uuid = str(uuid.uuid4())
    agent_id = input(f"Enter agent ID (default UUID: {generated_uuid}): ").strip() or generated_uuid
    protocol = input("Protocol TCP or UDP? (default: TCP): ").strip().upper() or 'TCP'
    if protocol not in ('TCP', 'UDP'):
        protocol = 'TCP'

    attack_choice = input("Enable attack simulation (massive REPORT burst)? (y/N): ").strip().lower()
    burst_count = 0
    if attack_choice == 'y':
        burst_count_text = input("How many REPORT messages for attack (default: 100): ").strip()
        burst_count = int(burst_count_text) if burst_count_text.isdigit() else 100

    hostname = socket.gethostname()
    
    print(f"Agent Configuration:")
    print(f"  ID: {agent_id}")
    print(f"  Protocol: {protocol}")
    print(f"  Hostname: {hostname}")
    print(f"  Report Interval: {REPORT_INTERVAL}s")
    print(f"  Connecting to {HOST}:{PORT}\n")
    
    try:
        if protocol == 'UDP':
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            client_socket.settimeout(2)
            client_socket.connect((HOST, PORT))
            print("UDP socket ready\n")
        else:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.connect((HOST, PORT))
            print("Connected to server\n")
        
        # Send HELLO message
        hello_msg = f"HELLO {agent_id} {hostname}"
        if protocol == 'UDP':
            response = send_message_udp(client_socket, hello_msg)
        else:
            response = send_message_tcp(client_socket, hello_msg)
        
        if response != 'OK':
            print(f"Registration failed: {response}")
            client_socket.close()
            return
        
        print(f"Successfully registered as {agent_id}\n")

        if burst_count > 0:
            run_attack_mode(client_socket, agent_id, protocol, burst_count)
        report_thread_obj = threading.Thread(
            target=report_thread,
            args=(client_socket, agent_id, protocol),
            daemon=True
        )
        report_thread_obj.start()
        print("Agent is running... Press Ctrl+C to disconnect\n")
        while True:
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                print("\n\nShutting down agent...")
                break
        
        # Send BYE message
        bye_msg = f"BYE {agent_id}"
        if protocol == 'UDP':
            response = send_message_udp(client_socket, bye_msg)
        else:
            response = send_message_tcp(client_socket, bye_msg)
        
        if response == 'OK':
            print("Successfully unregistered from server")
        else:
            print(f"Unregistration error: {response}")
    
    except ConnectionRefusedError:
        print(f"Error: Could not connect to server at {HOST}:{PORT}")
        print("Make sure the server is running")
    except Exception as e:
        print(f"Error: {e}")
    
    finally:
        try:
            client_socket.close()
        except:
            pass
        print("Connection closed")


if __name__ == '__main__':
    main()
