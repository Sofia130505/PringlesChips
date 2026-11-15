"""Motor sencillo de niveles, independiente del tutor IA."""
from __future__ import annotations
import json
import random
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "apps" / "frontend"
TRAIN_PATH = FRONTEND_DIR / "train.jsonl"
PROBLEMS_PER_LEVEL = 3
ISLAND_IDS = ["pirata", "hielo", "lava", "jungla", "robot", "espacio", "chuche", "desierto"]


class GameEngine:
    def __init__(self):
        self.problems_by_level = {i: [] for i in range(8)}
        self.active_session = None
        self._load_problems()

    def _load_problems(self):
        if not TRAIN_PATH.exists():
            raise FileNotFoundError(f"No encuentro {TRAIN_PATH}. Coloca train.jsonl en apps/frontend/")
        with TRAIN_PATH.open("r", encoding="utf-8-sig") as f:
            for line_number, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    problem = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"JSON inválido en train.jsonl, línea {line_number}: {exc}") from exc
                if problem.get("language") != "cat":
                    continue
                try:
                    level = int(problem.get("level"))
                except (TypeError, ValueError):
                    continue
                if level not in self.problems_by_level:
                    continue
                label = str(problem.get("label", "")).upper()
                if label not in {"A", "B", "C", "D", "E"}:
                    continue
                self.problems_by_level[level].append({"id": str(problem["id"]), "label": label})

    @staticmethod
    def _public_problem(problem):
        return {"id": problem["id"], "image": f"assets/problemas_img/{problem['id']}_cat.png"}

    def start_level(self, island_id, level_number):
        if island_id not in ISLAND_IDS:
            return {"status": "error", "message": "Isla no válida."}
        difficulty = ISLAND_IDS.index(island_id)
        pool = self.problems_by_level[difficulty]
        if len(pool) < PROBLEMS_PER_LEVEL:
            return {"status": "error", "message": f"No hay suficientes problemas en catalán para la dificultad {difficulty}."}
        selected = random.sample(pool, PROBLEMS_PER_LEVEL)
        self.active_session = {
            "island_id": island_id,
            "level_number": int(level_number),
            "problems": selected,
            "index": 0,
            "wrong_attempts": 0,
        }
        return {"status": "question", "question_number": 1, "total": PROBLEMS_PER_LEVEL,
                "problem": self._public_problem(selected[0])}

    def submit_level_answer(self, answer):
        session = self.active_session
        if not session:
            return {"status": "error", "message": "No hay ningún nivel activo."}
        answer = str(answer or "").upper()
        problem = session["problems"][session["index"]]
        if answer == problem["label"]:
            session["index"] += 1
            session["wrong_attempts"] = 0
            if session["index"] >= PROBLEMS_PER_LEVEL:
                self.active_session = None
                return {"status": "level_completed"}
            return {"status": "question", "question_number": session["index"] + 1,
                    "total": PROBLEMS_PER_LEVEL,
                    "problem": self._public_problem(session["problems"][session["index"]])}

        session["wrong_attempts"] += 1
        if session["wrong_attempts"] == 1:
            # Placeholder deliberado: aquí se podrá llamar al tutor IA en el futuro.
            return {"status": "hint", "message": "La IA te echa una mano", "problem": self._public_problem(problem)}

        self.active_session = None
        return {"status": "level_failed"}

    def cancel_level(self):
        self.active_session = None
        return {"status": "cancelled"}
