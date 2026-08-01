import json

import server as server_state


def read_events(since=None, until=None, event_type=None, agent_id=None, severity=None):
    events = []
    try:
        with open(server_state.EVENTS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if since and event['timestamp'] < since:
                    continue
                if until and event['timestamp'] > until:
                    continue
                if event_type and event['type'] != event_type:
                    continue
                if agent_id and event.get('agent_id') != agent_id:
                    continue
                if severity and event.get('severity') != severity:
                    continue

                events.append(event)
    except FileNotFoundError:
        pass

    return events


def summarize_events(events):
    summary = {'total': len(events), 'by_type': {}, 'by_severity': {}, 'by_source_ip': {}}
    for event in events:
        summary['by_type'][event['type']] = summary['by_type'].get(event['type'], 0) + 1
        sev = event.get('severity', 'unknown')
        summary['by_severity'][sev] = summary['by_severity'].get(sev, 0) + 1
        ip = event.get('source_ip')
        if ip:
            summary['by_source_ip'][ip] = summary['by_source_ip'].get(ip, 0) + 1
    return summary

def format_report(events, summary):
    lines = ["# Rapport de sécurité", "", f"Période analysée : {len(events)} événement(s)", ""]
    lines += ["## Par type"] + [f"- {t}: {c}" for t, c in sorted(summary['by_type'].items(), key=lambda x: -x[1])]
    lines += ["", "## Par sévérité"] + [f"- {s}: {c}" for s, c in sorted(summary['by_severity'].items(), key=lambda x: -x[1])]
    top_ips = sorted(summary['by_source_ip'].items(), key=lambda x: -x[1])[:10]
    lines += ["", "## Top IPs sources"] + [f"- {ip}: {c} événement(s)" for ip, c in top_ips]
    lines += ["", "## Timeline"]
    for e in events:
        agent = f" [{e.get('agent_id')}]" if e.get('agent_id') else ''
        lines.append(f"- {e['timestamp']} — {e['type']}{agent} (sévérité: {e.get('severity')})")
    return "\n".join(lines)