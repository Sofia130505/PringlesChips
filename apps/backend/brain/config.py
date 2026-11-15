"""Configuración del cerebro del copiloto.

Todo se lee de `config.env` en la raíz del repositorio (igual que en el repo de
la Datathon) y se puede pisar con variables de entorno, por ejemplo:

    LLM_PORT=9091 python3 apps/backend/main.py --check

Solo librería estándar: este módulo no importa nada fuera de `os` y `random`.
"""
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))        # apps/backend/brain
BACKEND_DIR = os.path.dirname(HERE)                      # apps/backend
ROOT = os.path.dirname(os.path.dirname(BACKEND_DIR))     # raíz del repositorio
ENV_FILE = os.path.join(ROOT, "config.env")

DEFAULTS = {
    # Servidores llama.cpp de la placa (systemd `math-llm` / `math-embed`)
    "LLM_HOST": "127.0.0.1",
    "LLM_PORT": "8081",
    "EMBED_HOST": "127.0.0.1",
    "EMBED_PORT": "8082",
    "VISION_HOST": "127.0.0.1",
    "VISION_PORT": "8083",
    # Tiempos máximos en segundos (la placa es lenta: 11 tok/s de lectura)
    "LLM_TIMEOUT": "120",
    "EMBED_TIMEOUT": "20",
    "HEALTH_TIMEOUT": "3",
    # Determinismo (los jueces exigen las mismas respuestas siempre)
    "SEED": "0",
    "FALLBACK_ANSWER": "D",
    "TIME_LIMIT_SECONDS": "60",
    # Embeddings: bge-small-en-v1.5, 384 dimensiones. Las consultas llevan
    # prefijo, los documentos guardados en el índice no.
    "EMBED_DIM": "384",
    "EMBED_BATCH": "8",
    "EMBED_QUERY_PREFIX": "Represent this sentence for searching relevant passages: ",
    # Rutas relativas a la raíz del repositorio
    "DATA_DIR": "data",
    "DB_PATH": "data/game_state.db",
    "INDEX_PATH": "data/index.db",
}


def _read_env_file(path):
    """Lee un `config.env` con líneas KEY=VALUE, comentarios con `#`."""
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


CONFIG = dict(DEFAULTS)
_ENV_VALUES = _read_env_file(ENV_FILE)
CONFIG.update(_ENV_VALUES)
for _key in list(CONFIG):
    if _key in os.environ:
        CONFIG[_key] = os.environ[_key]

# De dónde salió cada valor, para poder enseñarlo en `main.py --check`.
SOURCES = {key: ("config.env" if key in _ENV_VALUES else "por defecto")
           for key in DEFAULTS}


def number(key):
    """Valor numérico de una clave (`int(float(...))` para admitir "60.0")."""
    return int(float(CONFIG[key]))


def path(key):
    """Ruta absoluta de una clave; si es relativa se resuelve contra la raíz."""
    value = CONFIG[key]
    if os.path.isabs(value):
        return os.path.normpath(value)
    return os.path.normpath(os.path.join(ROOT, value))


def base_url(service):
    """`http://127.0.0.1:8081` para service="LLM", etc."""
    return "http://{}:{}".format(CONFIG[service + "_HOST"], CONFIG[service + "_PORT"])


def seed_random():
    """Fija la semilla global de `random` y la devuelve."""
    seed = number("SEED")
    random.seed(seed)
    return seed
