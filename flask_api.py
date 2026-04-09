import argparse
import socket
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, render_template, request

import server as server_state

app = Flask(__name__)


def is_port_open(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def maybe_start_monitor_server(auto_start):
    if not auto_start:
        return

    if is_port_open(server_state.HOST, server_state.PORT):
        print(
            f"[flask_api] Monitoring server already running on "
            f"{server_state.HOST}:{server_state.PORT}, reusing shared module state in this process only."
        )
        return

    thread = threading.Thread(target=server_state.main, daemon=True)
    thread.start()
    time.sleep(0.8)
    print(f"[flask_api] Monitoring server started in background on {server_state.HOST}:{server_state.PORT}")


def build_snapshot(alert_limit=20):
    with server_state.agents_lock:
        agents_copy = {agent_id: dict(info) for agent_id, info in server_state.agents.items()}

    with server_state.metrics_lock:
        total_reports_value = server_state.total_reports
        recent_error_count = len(server_state.error_timestamps)

    with server_state.alerts_lock:
        alerts_copy = list(server_state.alerts[-alert_limit:])

    active_agents = len(agents_copy)
    if active_agents > 0:
        avg_cpu = sum(info.get("cpu_pct", 0.0) for info in agents_copy.values()) / active_agents
        avg_ram = sum(info.get("ram_mb", 0.0) for info in agents_copy.values()) / active_agents
    else:
        avg_cpu = 0.0
        avg_ram = 0.0

    agent_rows = []
    for agent_id, info in sorted(agents_copy.items()):
        health = info.get("health", {})
        agent_rows.append(
            {
                "agent_id": agent_id,
                "hostname": info.get("hostname", ""),
                "protocol": info.get("protocol", ""),
                "addr": info.get("addr", ""),
                "cpu_pct": float(info.get("cpu_pct", 0.0)),
                "ram_mb": float(info.get("ram_mb", 0.0)),
                "last_report_time": float(info.get("last_report_time", 0.0)),
                "health": {
                    "timestamp": int(health.get("timestamp", 0)) if str(health.get("timestamp", "0")).isdigit() else 0,
                    "status": health.get("status", "UNKNOWN"),
                    "uptime_s": float(health.get("uptime_s", 0.0)),
                    "error_count": int(health.get("error_count", 0)),
                    "last_health_time": float(health.get("last_health_time", 0.0)),
                },
            }
        )

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "active_agents": active_agents,
            "avg_cpu_pct": round(avg_cpu, 2),
            "avg_ram_mb": round(avg_ram, 2),
            "total_reports": total_reports_value,
            "recent_error_count": recent_error_count,
        },
        "agents": agent_rows,
        "alerts": alerts_copy,
    }


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/overview", methods=["GET"])
def api_overview():
    limit = request.args.get("alert_limit", default=20, type=int)
    limit = max(1, min(200, limit))
    return jsonify(build_snapshot(alert_limit=limit))


@app.route("/api/stats", methods=["GET"])
def api_stats():
    return jsonify(build_snapshot(alert_limit=1)["summary"])


@app.route("/api/agents", methods=["GET"])
def api_agents():
    return jsonify(build_snapshot(alert_limit=1)["agents"])


@app.route("/api/alerts", methods=["GET"])
def api_alerts():
    limit = request.args.get("limit", default=20, type=int)
    limit = max(1, min(200, limit))
    return jsonify(build_snapshot(alert_limit=limit)["alerts"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flask API + dashboard for network monitoring TP")
    parser.add_argument("--host", default="127.0.0.1", help="Flask bind host")
    parser.add_argument("--port", default=8000, type=int, help="Flask bind port")
    parser.add_argument(
        "--no-monitor",
        action="store_true",
        help="Do not auto-start monitoring server in this process",
    )
    args = parser.parse_args()

    maybe_start_monitor_server(auto_start=not args.no_monitor)
    app.run(host=args.host, port=args.port, debug=False)
