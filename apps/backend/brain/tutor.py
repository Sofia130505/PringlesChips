"""El cerebro del copiloto: qué pregunta toca, cuándo se supera un nivel y qué pista.

Este módulo mantiene el diseño de juego que ya teníais (test inicial de 20
preguntas, 5 niveles por isla, 3 problemas por nivel, repaso final y accesorio
al llegar al 80%), pero cambia dos cosas que estaban mal:

1. **No llama al modelo para elegir pregunta.** Elegir es `random` sobre el
   banco de problemas, y las pistas usan el índice local (`rag.py`).
2. **No hay llamadas bloqueantes escondidas.** `hint()` es instantánea; la
   pista del modelo es `model_hint()` y el servidor web debe lanzarla en un
   hilo (tarda 5-30 s en la placa).

Ninguna función de aquí escribe en la red salvo `model_hint()`.
"""
import random

from . import client, config, llm, problems

ISLANDS_META = [
    {"id": 0, "name": "Isla Pirata", "accessory": "Sombrero de Capitán"},
    {"id": 1, "name": "Isla de Hielo", "accessory": "Bufanda Polar"},
    {"id": 2, "name": "Isla de Lava", "accessory": "Gafas Ignífugas"},
    {"id": 3, "name": "Isla de la Jungla", "accessory": "Brújula Antigua"},
    {"id": 4, "name": "Isla del Desierto", "accessory": "Turbante del Oasis"},
    {"id": 5, "name": "Isla de las Chuches", "accessory": "Bastón de Caramelo"},
    {"id": 6, "name": "Isla del Espacio", "accessory": "Casco de Astronauta"},
    {"id": 7, "name": "Isla de los Robots", "accessory": "Antena Cibernética"},
]

LEVELS_PER_ISLAND = 5          # 4 de 5 = 80% -> desbloquea el accesorio
PROBLEMS_PER_LEVEL = 3         # 3 problemas por nivel (~10 minutos)
MAX_PLACEMENT_QUESTIONS = 20   # tope del test inicial
QUESTIONS_PER_LEVEL = 2        # preguntas por nivel en el test inicial
CONSECUTIVE_WRONG_STOP = 2     # dos fallos seguidos y se acaba el test
UNLOCK_RATIO = 0.8


class Tutor:
    """Estado del juego y decisiones pedagógicas."""

    def __init__(self, by_level, store, index=None):
        self.by_level = by_level
        self.store = store
        self.index = index
        self.session = None

    # ------------------------------------------------------------------ utils
    def _pool(self, level):
        """Problemas de un nivel; si ese nivel está vacío, cualquiera sirve."""
        items = self.by_level.get(level) or []
        if items:
            return items
        return [problem for level_items in self.by_level.values() for problem in level_items]

    def _format(self, problem):
        """Problema listo para enviar: opciones A-E y la imagen si existe."""
        options = problem.get("options") or {}
        name = problems.image_name(problem)
        has_image = bool(problems.image_path(config.path("DATA_DIR"), problem))
        return {
            "id": problem["id"],
            "language": problem.get("language", "eng"),
            "level": int(problem.get("level", 0)),
            "text": problem.get("text", ""),
            "options": {letter: options.get(letter, "") for letter in problems.LETTERS},
            "image_url": "/data/images/" + name if has_image else "",
        }

    @staticmethod
    def _is_correct(problem, answer):
        return str(answer).strip().upper() == problem.get("label")

    # -------------------------------------------------- test inicial (nivel)
    def start_placement(self):
        """Empieza el test inicial: 20 preguntas como máximo, sin pistas."""
        self.session = {
            "mode": "placement",
            "current_level": 0,
            "questions_asked": 0,
            "consecutive_wrong": 0,
            "correct_per_level": {level: 0 for level in range(8)},
            "asked_per_level": {level: 0 for level in range(8)},
            "used_ids": set(),
            "current_problem": None,
        }
        return self._next_placement_question()

    def _next_placement_question(self):
        session = self.session
        level = session["current_level"]
        pool = [problem for problem in self._pool(level)
                if problem["id"] not in session["used_ids"]]
        if not pool:
            pool = self._pool(level)
        if not pool:
            self.session = None
            return {"error": "No hay problemas cargados en data/"}
        problem = random.choice(pool)
        session["used_ids"].add(problem["id"])
        session["current_problem"] = problem
        return {
            "status": "in_progress",
            "question_number": session["questions_asked"] + 1,
            "max_questions": MAX_PLACEMENT_QUESTIONS,
            "problem": self._format(problem),
        }

    def submit_placement_answer(self, answer):
        """Corrige una respuesta del test inicial. Sin feedback, a propósito."""
        session = self.session
        if not session or session["mode"] != "placement":
            return {"error": "No hay test inicial activo"}

        problem = session["current_problem"]
        correct = self._is_correct(problem, answer)
        session["questions_asked"] += 1
        level = session["current_level"]
        session["asked_per_level"][level] += 1

        if correct:
            session["correct_per_level"][level] += 1
            session["consecutive_wrong"] = 0
        else:
            session["consecutive_wrong"] += 1

        stop = (
            session["consecutive_wrong"] >= CONSECUTIVE_WRONG_STOP
            or session["questions_asked"] >= MAX_PLACEMENT_QUESTIONS
            or (level == 7 and session["asked_per_level"][7] >= QUESTIONS_PER_LEVEL)
        )

        if stop:
            assigned = 0
            for candidate in range(8):
                if session["correct_per_level"][candidate] >= 1:
                    assigned = candidate
            self.store.set_placement(assigned)
            self.session = None
            return {
                "status": "finished",
                "assigned_island": assigned,
                "island_info": ISLANDS_META[assigned],
            }

        if (session["asked_per_level"][level] >= QUESTIONS_PER_LEVEL
                and session["correct_per_level"][level] >= 1):
            session["current_level"] = min(7, level + 1)

        return self._next_placement_question()

    # ------------------------------------------------ niveles de una isla
    def start_level(self, island_id, level_idx):
        """Arranca un nivel: 3 problemas al azar del banco de esa isla."""
        island_id = int(island_id)
        level_idx = int(level_idx)
        if not 0 <= island_id < len(ISLANDS_META):
            return {"error": "Isla desconocida: {}".format(island_id)}
        if not 0 <= level_idx < LEVELS_PER_ISLAND:
            return {"error": "Nivel desconocido: {}".format(level_idx)}

        pool = self._pool(island_id)
        if not pool:
            return {"error": "No hay problemas para la isla {}".format(island_id)}
        selected = random.sample(pool, min(PROBLEMS_PER_LEVEL, len(pool)))
        self.session = {
            "mode": "level",
            "island_id": island_id,
            "level_idx": level_idx,
            "queue": selected,
            "failed_for_review": [],
            "in_review": False,
            "phase": "main",
            "current_problem": None,
        }
        return self._advance_level_queue()

    def _advance_level_queue(self):
        session = self.session
        if session["queue"]:
            session["current_problem"] = session["queue"].pop(0)
            session["phase"] = "review" if session["in_review"] else "main"
            return {
                "status": "next_problem",
                "phase": session["phase"],
                "remaining": len(session["queue"]) + 1,
                "problem": self._format(session["current_problem"]),
            }

        if session["failed_for_review"] and not session["in_review"]:
            session["queue"] = list(session["failed_for_review"])
            session["failed_for_review"] = []
            session["in_review"] = True
            return self._advance_level_queue()

        if session["failed_for_review"]:
            self.session = None
            return {
                "status": "level_failed",
                "message": "No acertaste todos en el repaso final. ¡Vuelve a intentarlo!",
            }

        reward = self._complete_level(session["island_id"], session["level_idx"])
        self.session = None
        return {"status": "level_completed", "reward": reward}

    def submit_level_answer(self, answer):
        """Corrige una respuesta de un nivel. La pista que devuelve es instantánea."""
        session = self.session
        if not session or session["mode"] != "level":
            return {"error": "No hay nivel activo"}

        problem = session["current_problem"]
        correct = self._is_correct(problem, answer)
        self.store.add_attempt(
            session["island_id"], problem["id"], session["phase"], correct,
            str(answer).strip().upper() == "DONT_KNOW",
        )

        if correct:
            result = self._advance_level_queue()
            result["feedback"] = "correct"
            return result

        if session["phase"] == "main":
            session["phase"] = "hint_retry"
            hint = self.hint(problem)
            return {
                "status": "retry_with_hint",
                "feedback": "incorrect",
                "hint": hint["text"],
                "hint_source": hint["source"],
                "similar_problem_id": (hint.get("example") or {}).get("id", ""),
                "problem": self._format(problem),
            }

        session["failed_for_review"].append(problem)
        result = self._advance_level_queue()
        result["feedback"] = "incorrect_moved_to_review"
        return result

    def _complete_level(self, island_id, level_idx):
        """Suma el nivel y desbloquea el accesorio al llegar al 80% de la isla."""
        completed = self.store.complete_level(island_id, level_idx)
        if (completed / float(LEVELS_PER_ISLAND)) < UNLOCK_RATIO:
            return {"unlocked": False}
        accessory = ISLANDS_META[island_id]["accessory"]
        if not self.store.add_accessory(accessory):
            return {"unlocked": False}
        return {"unlocked": True, "accessory": accessory,
                "island": ISLANDS_META[island_id]["name"]}

    # -------------------------------------------------------------- pistas
    def _similar(self, problem, k=3):
        """Problemas parecidos ya resueltos, del índice local (si existe)."""
        if not self.index or not len(self.index):
            return []
        try:
            return self.index.similar_easier(problem, k=k)
        except client.ServiceError:
            # Embeddings caídos: el juego sigue, solo que sin RAG.
            return []

    @staticmethod
    def _template_hint(problem, example=None):
        """Pista escrita a mano. Siempre disponible, cero segundos, sin modelo."""
        if example:
            label = example.get("label", "")
            value = (example.get("options") or {}).get(label, "")
            extra = " ({})".format(value) if value else ""
            return (
                "Fíjate en este problema parecido: «{}…». "
                "Su respuesta correcta era {}{}. Usa esa misma estrategia en el tuyo."
            ).format(example.get("text", "")[:160], label, extra)
        return (
            "Divide el problema en pasos: qué te dan, qué te piden y qué operación "
            "los une. Escribe los números antes de mirar las opciones."
        )

    def hint(self, problem):
        """Pista instantánea: problema parecido del índice + texto preparado.

        No llama al modelo: se puede usar en un handler HTTP sin bloquear.
        """
        similar = self._similar(problem)
        if similar:
            score, example = similar[0]
            return {
                "source": "rag",
                "text": self._template_hint(problem, example),
                "example": problems.public(example),
                "score": round(float(score), 3),
            }
        return {
            "source": "template",
            "text": self._template_hint(problem),
            "example": None,
            "score": None,
        }

    def model_hint(self, problem):
        """Pista redactada por el modelo. Tarda 5-30 s: el servidor la lanza en un hilo.

        Nunca lanza excepción: si algo falla devuelve la pista instantánea, así la
        página siempre tiene algo que enseñar.
        """
        fallback = self.hint(problem)
        similar = self._similar(problem)
        if not similar:
            fallback["source"] = "template"
            return fallback

        example = similar[0][1]
        try:
            text = llm.hint(problem, example)
        except client.ServiceError as error:
            fallback["error"] = str(error)
            return fallback

        # Rechazo del spoiler: si aparece el valor de la respuesta correcta, no vale.
        correct = str((problem.get("options") or {}).get(problem.get("label"), ""))
        if correct and len(correct) > 1 and correct in text:
            fallback.update({"source": "rejected", "rejected_text": text})
            return fallback

        return {"source": "model", "text": text,
                "example": problems.public(example), "score": round(float(similar[0][0]), 3)}

    # -------------------------------------------------------------- estado
    def state(self):
        """Perfil + progreso de las 8 islas (lo que el mapa necesita pintar)."""
        profile = self.store.profile()
        islands = []
        for meta in ISLANDS_META:
            levels = self.store.levels(meta["id"])
            percentage = int((sum(levels) / float(LEVELS_PER_ISLAND)) * 100)
            islands.append({
                **meta,
                "levels": levels,
                "completion_pct": percentage,
                "island_completed": percentage >= int(UNLOCK_RATIO * 100),
            })
        return {
            "placement_done": profile["placement_done"],
            "assigned_island": profile["assigned_island"],
            "unlocked_accessories": profile["unlocked_accessories"],
            "islands": islands,
        }

    def analytics(self):
        """Aciertos y fallos por isla."""
        return {"analytics_by_island": self.store.analytics()}

    def reset(self):
        """Vuelve al estado inicial (perfil, progreso e intentos)."""
        self.session = None
        self.store.reset()
        return self.state()
