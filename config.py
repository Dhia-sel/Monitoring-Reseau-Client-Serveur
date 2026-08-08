"""
Configuration centralisée du projet.

Toutes les valeurs sensibles ou variables selon l'environnement (tokens,
seuils, URLs) doivent venir d'ici, jamais être écrites en dur dans
server.py / client.py.

Les valeurs sont lues depuis des variables d'environnement (fichier .env
en local), avec une valeur par défaut de secours pour ne pas casser un
lancement rapide en dev.
"""
import os
from dotenv import load_dotenv

load_dotenv()  # charge le fichier .env s'il existe

# --- Authentification agent <-> serveur ---
# Token partagé que chaque agent doit fournir dans son message HELLO.
# En production, définis une vraie valeur secrète dans .env (jamais ici).
AGENT_AUTH_TOKEN = os.getenv('AGENT_AUTH_TOKEN', 'change-me-in-production')

# --- Événements de sécurité ---
# Fichier JSONL partagé par server.py et security_core.py (un événement par ligne).
EVENTS_FILE = os.getenv('EVENTS_FILE', 'events.jsonl')

# --- Détection flood / DoS (T1498 / T1499) ---
# Fenêtre glissante sur laquelle on compte le débit de connexions par IP.
FLOOD_WINDOW_SECONDS = float(os.getenv('FLOOD_WINDOW_SECONDS', '1.0'))
# Au-delà de ce débit (conn/s), on considère que ça sent la rafale suspecte
# mais on ne bloque pas encore (juste un avertissement).
FLOOD_THRESHOLD_WARN = int(os.getenv('FLOOD_THRESHOLD_WARN', '10'))
# Au-delà de ce débit, on bloque l'IP (flood confirmé).
FLOOD_THRESHOLD_BLOCK = int(os.getenv('FLOOD_THRESHOLD_BLOCK', '100'))
# Durée de blocage d'une IP après un flood confirmé.
BLOCK_DURATION_SECONDS = int(os.getenv('BLOCK_DURATION_SECONDS', '60'))

# --- Détection scan de ports/services (T1046) ---
# Une connexion est considérée comme une "sonde" (probe) si elle se ferme
# avant ce délai ET sans avoir transmis de données dans un sens ou l'autre.
# C'est la signature typique d'un scan de type "connect scan" (nmap -sT).
SCAN_PROBE_MAX_DURATION_SECONDS = float(os.getenv('SCAN_PROBE_MAX_DURATION_SECONDS', '0.5'))
# Fenêtre glissante sur laquelle on compte les sondes par IP.
SCAN_PROBE_WINDOW_SECONDS = float(os.getenv('SCAN_PROBE_WINDOW_SECONDS', '10'))
# Nombre de sondes dans la fenêtre à partir duquel on déclare un scan et on bloque.
SCAN_PROBE_THRESHOLD = int(os.getenv('SCAN_PROBE_THRESHOLD', '5'))

# --- Forwarder Splunk (HTTP Event Collector) ---
# URL du endpoint HEC "event". En local avec l'image Docker splunk/splunk,
# c'est https://localhost:8088/services/collector/event (TLS auto-signé).
SPLUNK_HEC_URL = os.getenv('SPLUNK_HEC_URL', 'https://localhost:8088/services/collector/event')
# Token HEC — à générer toi-même (uuid), jamais commité. Vide = forwarder désactivé.
SPLUNK_HEC_TOKEN = os.getenv('SPLUNK_HEC_TOKEN', '')
# Splunk Free en local utilise un certificat auto-signé : on ne vérifie pas
# le TLS par défaut en dev. Mets 'true' en environnement de prod avec un vrai certif.
SPLUNK_HEC_VERIFY_TLS = os.getenv('SPLUNK_HEC_VERIFY_TLS', 'false').lower() == 'true'
SPLUNK_HEC_SOURCE = os.getenv('SPLUNK_HEC_SOURCE', 'monitoring-reseau-client-serveur')
SPLUNK_HEC_SOURCETYPE = os.getenv('SPLUNK_HEC_SOURCETYPE', '_json')
# Index Splunk cible. Laisse vide pour utiliser l'index par défaut du token HEC.
SPLUNK_HEC_INDEX = os.getenv('SPLUNK_HEC_INDEX', '')
# Combien d'événements par requête HTTP au maximum.
SPLUNK_FORWARD_BATCH_SIZE = int(os.getenv('SPLUNK_FORWARD_BATCH_SIZE', '50'))
# Intervalle entre deux passages du forwarder (secondes) — "temps réel" au sens
# polling léger, pas un flux bloquant, donc pas de dépendance forte avec server.py.
SPLUNK_FORWARD_INTERVAL_SECONDS = float(os.getenv('SPLUNK_FORWARD_INTERVAL_SECONDS', '2'))
SPLUNK_FORWARD_MAX_RETRIES = int(os.getenv('SPLUNK_FORWARD_MAX_RETRIES', '3'))
# Fichier qui mémorise jusqu'où le forwarder a déjà lu dans events.jsonl,
# pour ne pas renvoyer deux fois un événement après un redémarrage.
SPLUNK_FORWARD_OFFSET_FILE = os.getenv('SPLUNK_FORWARD_OFFSET_FILE', 'events.jsonl.offset')