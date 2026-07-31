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