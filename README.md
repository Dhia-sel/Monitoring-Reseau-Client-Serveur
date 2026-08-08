# 🖥️ Mini-Projet Réseaux TP RT2 — Monitoring Réseau Client–Serveur

> Système de monitoring réseau distribué basé sur une architecture client–serveur TCP/UDP.  
> Chaque agent collecte périodiquement des métriques (CPU, RAM) et les envoie au serveur central.  
> Le serveur agrège les données, maintient la liste des agents actifs et affiche des statistiques.  
> Un dashboard web (extension) permet de visualiser les métriques en temps réel.

---

## 📋 Table des matières

- [1. Prérequis et installation](#1-prérequis-et-installation)
- [2. Lancer le projet](#2-lancer-le-projet)
- [3. Fonctionnalités obligatoires](#3-fonctionnalités-obligatoires)
- [4. Extensions implémentées](#4-extensions-implémentées)
- [5. Spécification du protocole](#5-spécification-du-protocole)
- [6. Tests](#6-tests)
- [7. Choix techniques](#7-choix-techniques)
- [8. Structure du projet](#8-structure-du-projet)
- [9. Conformité au cahier des charges](#9-conformité-au-cahier-des-charges)
- [10. Auteurs](#10-auteurs)

---

## 1. Prérequis et installation

### Prérequis

- Python 3.8+

### Dépendances

Le cœur du projet (serveur + clients + tests) utilise **uniquement la bibliothèque standard** Python — aucun `pip install` requis pour le fonctionnement de base.

Le dashboard web (extension optionnelle) nécessite Flask :

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

---

## 2. Lancer le projet

### 2.1 Serveur principal

```bash
python server.py
```

Le serveur démarre sur `127.0.0.1:5051` en mode TCP + UDP.

Configuration par défaut :

| Paramètre             | Valeur      | Description                |
| --------------------- | ----------- | -------------------------- |
| `HOST`                | `127.0.0.1` | Adresse d'écoute           |
| `PORT`                | `5051`      | Port TCP + UDP             |
| `STATS_INTERVAL`      | `10s`       | Intervalle statistiques    |
| `ACTIVE_WINDOW`       | `30s`       | Fenêtre d'activité (3 × T) |
| `CPU_ALERT_THRESHOLD` | `85.0%`     | Seuil alerte CPU           |

### 2.2 Dashboard web (extension optionnelle)

Après activation du venv :

```bash
python flask_api.py
```

Accès : `http://127.0.0.1:8000`

Par défaut, `flask_api.py` démarre automatiquement `server.py` en arrière-plan si rien n'écoute déjà sur `127.0.0.1:5051`.

En pratique, vous avez 2 modes :

- **Mode simple (recommandé)** : lancer uniquement `python flask_api.py`, puis lancer les clients.
- **Mode manuel** : lancer `python server.py` séparément, puis `python flask_api.py --no-monitor`.

### 2.3 Démarrer un agent

```bash
python client.py
```

L'agent demande interactivement :

- `agent_id` (UUID auto-généré proposé par défaut)
- Protocole : `TCP` (défaut) ou `UDP`
- Mode attaque (burst massif de REPORT) : `y/N`

Ou utiliser le client simplifié avec métriques simulées (aléatoires) :

```bash
python client_simple.py
```

### 2.4 Exemple de séquence complète (mode simple recommandé)

**Terminal 1 — Dashboard + serveur auto-démarré :**

```bash
python flask_api.py
```

### 2.5 Lancer avec Docker

1. Copier le modèle d'environnement :

```bash
copy .env.example .env
```

2. Mettre à jour les valeurs sensibles dans `.env` :
   - `AGENT_AUTH_TOKEN`
   - `SPLUNK_PASSWORD`
   - `SPLUNK_HEC_TOKEN`

3. Démarrer les services Docker :

```bash
docker compose up --build
```

- Le dashboard est disponible sur `http://localhost:8000`
- Le serveur TCP/UDP est accessible sur `localhost:5051`
- Le proxy TLS écoute sur `localhost:6000`
- Splunk Web est accessible sur `http://localhost:8001`
- Splunk HEC est accessible sur `https://localhost:8088`

> Si `SPLUNK_HEC_TOKEN` n'est pas généré automatiquement par l'image Splunk, crée un token HEC dans l'interface Splunk et place-le dans `.env`.

> Le service `monitor` auto-démarre le serveur de monitoring interne via `flask_api.py`.

> Le service `forwarder` lit `events.jsonl` et tente d'envoyer les événements vers Splunk HEC.

**Terminal 2 — Agent 1 :**

```bash
python client.py
# → Enter agent ID: agent1
# → Protocol TCP or UDP? TCP
# → Enable attack simulation? N
```

**Terminal 3 — Agent 2 :**

```bash
python client_simple.py
```

Ouvrir `http://127.0.0.1:8000` pour voir les métriques en temps réel.

> Si vous préférez séparer les processus :
>
> 1. `python server.py`
> 2. `python flask_api.py --no-monitor`

---

## 3. Fonctionnalités obligatoires

### Architecture

- ✅ Communication **TCP** (primaire)
- ✅ Protocole `HELLO` / `REPORT` / `BYE`
- ✅ Gestion de **plusieurs connexions simultanées** via threads
- ✅ Un thread par client TCP côté serveur
- ✅ **Robustesse** : le serveur ne s'arrête jamais en cas d'erreur client
- ✅ **Validation stricte** des messages (format, plages de valeurs)

### Statistiques périodiques (toutes les 10s)

Le serveur affiche en console :

- Nombre d'agents actifs
- Moyenne CPU (%)
- Moyenne RAM (MB)
- Total de `REPORT` reçus
- Alertes récentes

### Règle d'activité d'un agent

Un agent est considéré **actif** si un `REPORT` est reçu dans une fenêtre de **3 × T secondes** (T = 10s → fenêtre = 30s).  
Passé ce délai sans rapport, l'agent est automatiquement supprimé de la liste active.

---

## 4. Extensions implémentées

### A. Mode UDP

- Clients TCP et UDP gérés **simultanément** par le même serveur sur le même port
- Protocole identique : `HELLO`, `REPORT`, `BYE`
- UDP est sans état (stateless) côté serveur : pas de persistance de connexion
- Permet la comparaison TCP vs UDP : fiabilité vs latence

### B. Auto-cleanup des agents inactifs

- Thread daemon `inactive_cleanup_thread()` parcourt les agents toutes les **5s**
- Supprime automatiquement tout agent avec `(now - last_report_time) >= 30s`
- Log de chaque suppression en console

### C. Export CSV des statistiques

- Fichier `stats_export.csv` créé et mis à jour automatiquement
- Colonnes : `timestamp, active_agents, avg_cpu_pct, avg_ram_mb, total_reports`
- Une ligne ajoutée toutes les **10s**
- Format compatible Excel / Pandas

### D. UUID comme agent_id

- Les agents peuvent fournir un UUID au lieu d'un identifiant manuel
- `client.py` génère et propose un UUID automatiquement si le champ est laissé vide
- Aucune contrainte de format sur `agent_id` (sauf : pas d'espaces)

### E. Simulation d'attaque

- Mode "attack" dans `client.py` : envoi massif de `REPORT` en rafale
- Paramétrable : nombre de messages (défaut : 100)
- Permet de mesurer la capacité du serveur et de tester sa robustesse face à un flood

### F. Système d'alertes

Trois types d'alertes générées automatiquement par le serveur :

| Type             | Déclencheur                                            |
| ---------------- | ------------------------------------------------------ |
| `CPU_HIGH`       | `cpu_pct` dépasse `CPU_ALERT_THRESHOLD` (défaut : 85%) |
| `AGENT_INACTIVE` | Un agent est supprimé pour inactivité prolongée        |
| `ERROR_STORM`    | Trop de réponses `ERROR` dans une fenêtre courte       |

Les alertes sont :

- Affichées en temps réel dans la console serveur
- Incluses dans le bloc de statistiques périodiques
- Exposées via l'API REST du dashboard (`/api/alerts`)

Paramètres configurables dans `server.py` :

```python
CPU_ALERT_THRESHOLD  = 85.0   # % CPU
ERROR_ALERT_THRESHOLD = 5     # nombre d'erreurs
ERROR_ALERT_WINDOW   = 10     # secondes
ERROR_ALERT_COOLDOWN = 10     # secondes entre deux alertes ERROR_STORM
```

### G. Agent health metadata

Nouveau message optionnel `HEALTH` pour enrichir l'observabilité sans modifier le protocole de base :

```
HEALTH <agent_id> <timestamp> <status> <uptime_s> <error_count>
```

Exemple :

```
HEALTH agent1 1700000001 DEGRADED 120.5 2
```

- Le serveur reste **100% compatible** avec le cahier des charges : l'activité est calculée sur `REPORT` uniquement
- Si un serveur ne supporte pas `HEALTH`, le client continue en mode protocole de base
- Statuts valides : `OK`, `DEGRADED`, `CRITICAL`

### H. Web Dashboard (Flask + Chart.js)

Interface web temps réel accessible sur `http://127.0.0.1:8000` :

- **Tableau** des agents actifs : `agent_id`, hostname, protocole, CPU, RAM, statut health
- **Graphique CPU** : évolution de la moyenne CPU au fil du temps
- **Graphique RAM** : évolution de la moyenne RAM au fil du temps
- **Compteur** d'agents actifs mis à jour en temps réel
- **Panneau alertes** : affichage des alertes `CPU_HIGH`, `AGENT_INACTIVE`, `ERROR_STORM`
- Rafraîchissement automatique toutes les **3 secondes** (polling)

Endpoints REST exposés par `flask_api.py` 

| Endpoint      | Méthode | Description                         |
| ------------- | ------- | ----------------------------------- |
| `/`           | GET     | Page dashboard HTML                 |
| `/api/agents` | GET     | Liste des agents actifs + métriques |
| `/api/stats`  | GET     | Moyenne CPU, RAM, total reports     |
| `/api/alerts` | GET     | 20 dernières alertes                |

---

## 5. Spécification du protocole

### Messages Client → Serveur

| Message  | Format                                                            | Exemple                                     |
| -------- | ----------------------------------------------------------------- | ------------------------------------------- |
| `HELLO`  | `HELLO <agent_id> <hostname>`                                     | `HELLO agent1 PC-LAB`                       |
| `REPORT` | `REPORT <agent_id> <timestamp> <cpu_pct> <ram_mb>`                | `REPORT agent1 1700000000 25.5 2048`        |
| `HEALTH` | `HEALTH <agent_id> <timestamp> <status> <uptime_s> <error_count>` | `HEALTH agent1 1700000001 DEGRADED 120.5 2` |
| `BYE`    | `BYE <agent_id>`                                                  | `BYE agent1`                                |

### Réponses Serveur → Client

| Réponse | Signification            |
| ------- | ------------------------ |
| `OK`    | Message accepté          |
| `ERROR` | Format invalide ou rejet |

### Contraintes de validation

| Champ         | Contrainte                                            |
| ------------- | ----------------------------------------------------- |
| `agent_id`    | Sans espaces (alphanumérique, `-`, `_`, UUID accepté) |
| `cpu_pct`     | Réel dans `[0.0, 100.0]`                              |
| `ram_mb`      | Réel ≥ `0.0`                                          |
| `timestamp`   | Entier (epoch secondes)                               |
| `status`      | `OK`, `DEGRADED` ou `CRITICAL` uniquement             |
| `uptime_s`    | Réel ≥ `0.0`                                          |
| `error_count` | Entier ≥ `0`                                          |

### Exemple d'échange complet

```
Client  →  HELLO agent1 PC-LAB
Serveur →  OK

Client  →  REPORT agent1 1700000000 25.5 2048
Serveur →  OK

Client  →  HEALTH agent1 1700000001 OK 3600.0 0
Serveur →  OK

Client  →  BYE agent1
Serveur →  OK
```

---

## 6. Tests

### Lancer les tests

```bash
python test_suite.py
```

> ⚠️ Le serveur `server.py` doit être démarré avant de lancer les tests.

### Tests obligatoires

| #   | Test                 | Description                            | Statut |
| --- | -------------------- | -------------------------------------- | ------ |
| 1   | Single Client        | Connexion, HELLO, REPORT, BYE          | ✅     |
| 2   | Multiple Clients     | 3+ clients simultanément               | ✅     |
| 3   | Malformed Messages   | HELLO incomplet, REPORT invalide, etc. | ✅     |
| 4   | Unregistered Agent   | REPORT sans HELLO préalable            | ✅     |
| 5   | Metric Validation    | CPU > 100, RAM < 0, etc.               | ✅     |
| 6   | Disconnect/Reconnect | Même `agent_id`, reconnexion           | ✅     |

### Tests d'extensions

| #   | Test                  | Description                       | Statut |
| --- | --------------------- | --------------------------------- | ------ |
| 7   | UDP Flow              | HELLO / REPORT / BYE en UDP       | ✅     |
| 8   | UUID Agent ID         | UUID comme `agent_id`             | ✅     |
| 9   | Abrupt Disconnect     | Fermeture sans BYE                | ✅     |
| 10  | Average Calculation   | Vérification des moyennes CPU/RAM | ✅     |
| 11  | Inactivity Detection  | Auto-suppression après 3×T        | ✅     |
| 12  | CPU Alert             | Déclenchement si CPU > seuil      | ✅     |
| 13  | Inactive Alert        | Alerte lors suppression inactive  | ✅     |
| 14  | Error Storm Alert     | Trop de réponses ERROR            | ✅     |
| 15  | Health Metadata Valid | HEALTH accepté et stocké          | ✅     |
| 16  | Health Malformed      | HEALTH mal formé rejeté           | ✅     |
| 17  | Health Unregistered   | HEALTH agent inconnu rejeté       | ✅     |

> Le dashboard web est testé visuellement lors de la démo (pas de tests automatisés HTTP).

---

## 7. Choix techniques

### Collecte de métriques sans bibliothèque externe

Le projet respecte l'exigence **"bibliothèques standards uniquement"** pour le cœur du TP :

| OS      | CPU                         | RAM                                             |
| ------- | --------------------------- | ----------------------------------------------- |
| Windows | `typeperf` via `subprocess` | `ctypes.windll.kernel32.GlobalMemoryStatusEx()` |
| Linux   | `/proc/stat`                | `/proc/meminfo`                                 |
| macOS   | `sysctl`                    | `vm_stat`                                       |

### Gestion de la concurrence

- Un `threading.Thread` par client TCP côté serveur
- `threading.Lock` pour tout accès au dictionnaire `agents` et aux compteurs globaux
- Threads daemon pour : cleanup inactivité, statistiques, listener UDP

### Robustesse

- Toute exception levée dans un thread client est capturée localement → le serveur continue
- Timeout inactivité (30s) → suppression automatique des agents fantômes
- Validation stricte de chaque champ → réponse `ERROR` immédiate en cas de problème

### Dashboard (extension)

- `flask_api.py` importe directement `agents`, `alerts`, `total_reports` depuis `server.py`
- Aucune duplication de données : Flask lit l'état en mémoire partagée
- Polling côté navigateur toutes les 3s via `fetch()` JavaScript natif
- Chart.js chargé via CDN — aucun build tool requis

---

## 8. Structure du projet

```
.
├── server.py              # Serveur TCP + UDP (cœur du projet)
│   ├── handle_client()        # Thread-handler par client TCP
│   ├── udp_listener()         # Thread daemon UDP
│   ├── statistics_thread()    # Statistiques toutes les 10s
│   └── inactive_cleanup_thread()  # Suppression agents inactifs
│
├── client.py              # Agent complet (métriques réelles + HEALTH)
│   ├── get_cpu_usage_pct()    # Cross-platform sans psutil
│   ├── get_used_memory_mb()
│   └── run_attack_mode()      # Simulation d'attaque
│
├── client_simple.py       # Agent simplifié (métriques aléatoires)
│
├── flask_api.py           # Dashboard web (extension Flask)
│
├── templates/
│   └── dashboard.html     # Interface Chart.js (polling toutes les 3s)
│
├── test_suite.py          # 17 tests (6 obligatoires + 11 extensions)
│
├── stats_export.csv       # Généré automatiquement par server.py
├── requirements.txt       # flask>=2.0
├── run_demo.bat           # Lancement rapide Windows
└── README.md              # Ce fichier
```

---

## 9. Conformité au cahier des charges

### Obligatoire ✅

- Monitoring distribué client–serveur TCP
- Protocole `HELLO` / `REPORT` / `BYE`
- Gestion des threads (1 par client TCP)
- Validation robuste des entrées
- Statistiques périodiques (avg CPU, avg RAM, agents actifs)
- 6 tests obligatoires démontrés
- Bibliothèques standards uniquement (cœur du projet)

### Extensions ✅

| Extension       | Description                                              |
| --------------- | -------------------------------------------------------- |
| UDP             | Protocole identique sur UDP, même port                   |
| Inactivité      | Auto-cleanup après 3×T secondes                          |
| CSV             | Export automatique `stats_export.csv`                    |
| UUID            | Support identifiant UUID pour `agent_id`                 |
| Attaque         | Mode burst de `REPORT` pour tester la robustesse         |
| Alertes         | `CPU_HIGH`, `AGENT_INACTIVE`, `ERROR_STORM`              |
| Health metadata | Message `HEALTH` optionnel (status, uptime, error_count) |
| Web dashboard   | Flask API + Chart.js, temps réel sur port 8000           |

---

## 10. Auteurs

**AZZA KACHBOURI** — **DHIA SELMI**  
Mini-Projet Réseaux — TP RT2
