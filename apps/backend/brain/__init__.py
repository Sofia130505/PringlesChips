"""Cerebro del copiloto matemático (M3Kang + Arduino UNO Q).

Esto es lo que el servidor web de tu compañero tiene que usar. No abre ningún
puerto: solo carga datos, habla con los modelos de la placa y decide.

    import sys
    sys.path.insert(0, "apps/backend")
    from brain import build_brain

    tutor = build_brain()
    tutor.state()                     # perfil + progreso de las 8 islas
    tutor.start_placement()           # test inicial
    tutor.submit_placement_answer("C")
    tutor.start_level(0, 0)           # isla 0, nivel 0
    tutor.submit_level_answer("B")    # -> next_problem / retry_with_hint / ...
    tutor.hint(problem)               # pista instantánea (sin modelo)
    tutor.model_hint(problem)         # pista del modelo: ¡en un hilo!
    tutor.analytics()                 # aciertos y fallos por isla
    tutor.reset()

Compara los `/health` de 8081 y 8082 con `brain.services.status()` antes de
empezar, y no llames a `model_hint()` dentro de un handler HTTP.
"""
import os

from . import config, problems, services
from .rag import Index
from .store import Store
from .tutor import Tutor

__all__ = [
    "build_brain",
    "Tutor",
    "Store",
    "Index",
    "config",
    "problems",
    "services",
]


def build_brain(with_index=True):
    """Carga problemas, base de datos e índice, y devuelve el `Tutor` listo."""
    config.seed_random()
    loaded = problems.load_all(config.path("DATA_DIR"))
    store = Store(config.path("DB_PATH"), islands=8, levels_per_island=5)

    index = None
    index_path = config.path("INDEX_PATH")
    if with_index and os.path.exists(index_path):
        index = Index(index_path)

    tutor = Tutor(loaded["by_level"], store, index)
    tutor.loaded = loaded
    return tutor
