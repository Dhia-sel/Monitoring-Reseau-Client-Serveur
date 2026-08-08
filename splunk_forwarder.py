"""
Forwarder Splunk (HTTP Event Collector) pour events.jsonl.

Pourquoi un module séparé plutôt qu'un envoi direct depuis server.py /
security_core.py :
- Découplage : si Splunk est indisponible, ni le serveur ni le proxy ne
  doivent ralentir ou planter à cause de ça. Ce forwarder lit events.jsonl
  de façon totalement indépendante, en tâche de fond.
- "Temps réel" ici veut dire : polling léger toutes les
  SPLUNK_FORWARD_INTERVAL_SECONDS (2s par défaut), pas un flux bloquant.
  Largement suffisant pour du reporting/alerting, et beaucoup plus robuste
  qu'un vrai stream à maintenir.
- Zéro perte d'événement : l'offset de lecture n'avance que si Splunk a
  confirmé la réception (HTTP 200 + code 0). Si Splunk est injoignable, on
  retente au prochain passage sans rien perdre ni dupliquer.
"""
import json
import time
from datetime import datetime

import requests

import config


def load_offset(offset_file):
    try:
        with open(offset_file, 'r', encoding='utf-8') as f:
            return int(f.read().strip() or 0)
    except (FileNotFoundError, ValueError):
        return 0


def save_offset(offset_file, offset):
    with open(offset_file, 'w', encoding='utf-8') as f:
        f.write(str(offset))


def read_new_events(events_file, offset, max_events):
    """Lit jusqu'à max_events lignes JSON complètes depuis offset.

    Une ligne malformée est ignorée mais on avance quand même dessus (pour
    ne pas rester bloqué indéfiniment sur une ligne corrompue). Une ligne
    incomplète en fin de fichier (écriture en cours côté server.py) n'est
    PAS consommée : on s'arrête avant, pour ne jamais couper un événement
    JSON en deux morceaux.
    """
    events = []
    new_offset = offset
    try:
        with open(events_file, 'r', encoding='utf-8') as f:
            f.seek(offset)
            while len(events) < max_events:
                line = f.readline()
                if not line:
                    break
                if not line.endswith('\n'):
                    break  # ligne incomplète, écriture probablement en cours
                new_offset = f.tell()
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"[FORWARDER] Ligne JSON invalide ignorée: {line[:80]}")
    except FileNotFoundError:
        pass
    return events, new_offset


def _event_epoch_time(event):
    ts = event.get('timestamp')
    if ts:
        try:
            return datetime.fromisoformat(ts).timestamp()
        except (ValueError, TypeError):
            pass
    return time.time()


def build_hec_payload(event):
    payload = {
        'time': _event_epoch_time(event),
        'source': config.SPLUNK_HEC_SOURCE,
        'sourcetype': config.SPLUNK_HEC_SOURCETYPE,
        'event': event,
    }
    if config.SPLUNK_HEC_INDEX:
        payload['index'] = config.SPLUNK_HEC_INDEX
    return payload


def send_batch(events):
    """Envoie un lot d'événements à Splunk HEC. Retourne True si Splunk a
    confirmé la réception de tout le lot."""
    if not events:
        return True
    if not config.SPLUNK_HEC_TOKEN:
        print("[FORWARDER] SPLUNK_HEC_TOKEN non configuré — envoi ignoré.")
        return False

    # HEC accepte plusieurs objets JSON concaténés (sans séparateur) dans un seul body.
    body = ''.join(json.dumps(build_hec_payload(e)) for e in events)
    headers = {'Authorization': f'Splunk {config.SPLUNK_HEC_TOKEN}'}

    for attempt in range(1, config.SPLUNK_FORWARD_MAX_RETRIES + 1):
        try:
            response = requests.post(
                config.SPLUNK_HEC_URL,
                data=body,
                headers=headers,
                verify=config.SPLUNK_HEC_VERIFY_TLS,
                timeout=5,
            )
            if response.status_code == 200 and response.json().get('code') == 0:
                return True
            print(
                f"[FORWARDER] Refus Splunk (tentative {attempt}/{config.SPLUNK_FORWARD_MAX_RETRIES}): "
                f"{response.status_code} {response.text[:200]}"
            )
        except requests.RequestException as e:
            print(f"[FORWARDER] Erreur réseau (tentative {attempt}/{config.SPLUNK_FORWARD_MAX_RETRIES}): {e}")
        time.sleep(min(2 ** attempt, 10))
    return False


def run_once(events_file=None, offset_file=None):
    """Un seul passage : lit les nouveaux événements, les envoie, avance
    l'offset seulement en cas de succès. Retourne le nombre d'événements
    envoyés avec succès (0 si rien de nouveau ou en cas d'échec)."""
    events_file = events_file or config.EVENTS_FILE
    offset_file = offset_file or config.SPLUNK_FORWARD_OFFSET_FILE

    offset = load_offset(offset_file)
    events, new_offset = read_new_events(events_file, offset, config.SPLUNK_FORWARD_BATCH_SIZE)

    if not events:
        return 0

    if send_batch(events):
        save_offset(offset_file, new_offset)
        print(f"[FORWARDER] {len(events)} événement(s) envoyé(s) à Splunk.")
        return len(events)

    print(f"[FORWARDER] Échec d'envoi — {len(events)} événement(s) seront retentés au prochain passage.")
    return 0


def main():
    print(f"[FORWARDER] Démarrage — source: {config.EVENTS_FILE} -> {config.SPLUNK_HEC_URL}")
    if not config.SPLUNK_HEC_TOKEN:
        print("[FORWARDER] ATTENTION: SPLUNK_HEC_TOKEN vide, aucun événement ne sera envoyé.")
    try:
        while True:
            run_once()
            time.sleep(config.SPLUNK_FORWARD_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n[FORWARDER] Arrêt demandé.")


if __name__ == '__main__':
    main()