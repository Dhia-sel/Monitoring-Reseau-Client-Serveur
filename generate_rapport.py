import argparse
from events_store import read_events, summarize_events


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


def main():
    parser = argparse.ArgumentParser(description="Génère un rapport de sécurité depuis events.jsonl")
    parser.add_argument("--since"); parser.add_argument("--until")
    parser.add_argument("--output", default="security_report.md")
    args = parser.parse_args()

    events = read_events(since=args.since, until=args.until)
    summary = summarize_events(events)
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(format_report(events, summary))
    print(f"Rapport généré : {args.output} ({len(events)} événements)")


if __name__ == '__main__':
    main()