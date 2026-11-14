import json
import os
import random
import sqlite3

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "game_state.db")

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

LEVELS_PER_ISLAND = 5      # 4 completados = 80% -> desbloquea accesorio
PROBLEMS_PER_LEVEL = 3     # 3 problemas por nivel (~10 min máx.)

class GameEngine:
    def __init__(self):
        self.problems_by_island = {i: [] for i in range(8)}
        self._load_problems()
        self._init_db()
        self.active_session = None

    def _load_problems(self):
        """Lee train.jsonl / val.jsonl (o sample_problems.jsonl) y agrupa por nivel 0-7."""
        loaded = 0
        for fname in ["train.jsonl", "val.jsonl", "sample_problems.jsonl"]:
            path = os.path.join(DATA_DIR, fname)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        prob = json.loads(line)
                        lvl = int(prob.get("level", 0))
                        if 0 <= lvl <= 7:
                            self.problems_by_island[lvl].append(prob)
                            loaded += 1
            if loaded > 0 and fname != "train.jsonl":
                break

        # Si alguna isla queda vacía (ej. usando sample_problems.jsonl), rellena con los que haya
        all_probs = [p for plist in self.problems_by_island.values() for p in plist]
        for i in range(8):
            if not self.problems_by_island[i] and all_probs:
                self.problems_by_island[i] = list(all_probs)

    def _get_conn(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS profile (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    placement_done INTEGER DEFAULT 0,
                    assigned_island INTEGER DEFAULT 0,
                    unlocked_accessories TEXT DEFAULT '[]'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS island_progress (
                    island_id INTEGER,
                    level_idx INTEGER,
                    completed INTEGER DEFAULT 0,
                    PRIMARY KEY (island_id, level_idx)
                )
            """)
            conn.execute("INSERT OR IGNORE INTO profile (id) VALUES (1)")
            for i in range(8):
                for lvl in range(LEVELS_PER_ISLAND):
                    conn.execute(
                        "INSERT OR IGNORE INTO island_progress (island_id, level_idx, completed) VALUES (?, ?, 0)",
                        (i, lvl)
                    )

    def _format_problem(self, prob):
        opts = prob.get("options") or {}
        img_name = f"{prob['id']}_{prob.get('language', 'eng')}.png"
        img_url = f"/data/images/{img_name}" if os.path.exists(os.path.join(DATA_DIR, "images", img_name)) else ""
        return {
            "id": prob["id"],
            "level": int(prob.get("level", 0)),
            "text": prob.get("text", ""),
            "options": {
                "A": opts.get("A", ""),
                "B": opts.get("B", ""),
                "C": opts.get("C", ""),
                "D": opts.get("D", ""),
                "E": opts.get("E", ""),
            },
            "image_url": img_url
        }

    # --- TEST INICIAL (MÁX. 20 PREGUNTAS, SIN FEEDBACK) ---
    def start_placement(self):
        self.active_session = {
            "mode": "placement",
            "current_level": 0,
            "questions_asked": 0,
            "consecutive_wrong": 0,
            "correct_per_level": {i: 0 for i in range(8)},
            "asked_per_level": {i: 0 for i in range(8)},
            "used_ids": set(),
            "current_problem": None
        }
        return self._next_placement_question()

    def _next_placement_question(self):
        s = self.active_session
        lvl = s["current_level"]
        pool = [p for p in self.problems_by_island[lvl] if p["id"] not in s["used_ids"]]
        if not pool:
            pool = self.problems_by_island[lvl]
        prob = random.choice(pool)
        s["used_ids"].add(prob["id"])
        s["current_problem"] = prob
        return {
            "status": "in_progress",
            "question_number": s["questions_asked"] + 1,
            "max_questions": 20,
            "problem": self._format_problem(prob)
        }

    def submit_placement_answer(self, answer):
        s = self.active_session
        if not s or s["mode"] != "placement":
            return {"error": "No hay test inicial activo"}

        prob = s["current_problem"]
        is_correct = (answer == prob.get("label"))
        s["questions_asked"] += 1
        lvl = s["current_level"]
        s["asked_per_level"][lvl] += 1

        if is_correct:
            s["correct_per_level"][lvl] += 1
            s["consecutive_wrong"] = 0
        else:
            s["consecutive_wrong"] += 1

        stop = (
            s["consecutive_wrong"] >= 2
            or s["questions_asked"] >= 20
            or (lvl == 7 and s["asked_per_level"][7] >= 2)
        )

        if stop:
            assigned = 0
            for i in range(8):
                if s["correct_per_level"][i] >= 1:
                    assigned = i
            with self._get_conn() as conn:
                conn.execute(
                    "UPDATE profile SET placement_done = 1, assigned_island = ? WHERE id = 1",
                    (assigned,)
                )
            self.active_session = None
            return {
                "status": "finished",
                "assigned_island": assigned,
                "island_info": ISLANDS_META[assigned]
            }

        if s["asked_per_level"][lvl] >= 2 and s["correct_per_level"][lvl] >= 1:
            s["current_level"] = min(7, lvl + 1)

        return self._next_placement_question()

    # --- NIVELES DENTRO DE CADA ISLA ---
    def start_level(self, island_id, level_idx):
        pool = self.problems_by_island[island_id]
        selected = random.sample(pool, min(PROBLEMS_PER_LEVEL, len(pool)))
        self.active_session = {
            "mode": "level",
            "island_id": island_id,
            "level_idx": level_idx,
            "queue": selected,
            "failed_for_review": [],
            "in_review": False,
            "phase": "main",
            "current_problem": None
        }
        return self._advance_level_queue()

    def _advance_level_queue(self):
        s = self.active_session
        if s["queue"]:
            s["current_problem"] = s["queue"].pop(0)
            s["phase"] = "review" if s["in_review"] else "main"
            return {
                "status": "next_problem",
                "phase": s["phase"],
                "remaining": len(s["queue"]) + 1,
                "problem": self._format_problem(s["current_problem"])
            }

        if s["failed_for_review"] and not s["in_review"]:
            s["queue"] = list(s["failed_for_review"])
            s["failed_for_review"] = []
            s["in_review"] = True
            return self._advance_level_queue()

        if s["failed_for_review"]:
            self.active_session = None
            return {
                "status": "level_failed",
                "message": "No acertaste todos en el repaso final. ¡Vuelve a intentarlo!"
            }

        reward = self._complete_level(s["island_id"], s["level_idx"])
        self.active_session = None
        return {"status": "level_completed", "reward": reward}

    def submit_level_answer(self, answer):
        s = self.active_session
        if not s or s["mode"] != "level":
            return {"error": "No hay nivel activo"}

        prob = s["current_problem"]
        if answer == prob.get("label"):
            res = self._advance_level_queue()
            res["feedback"] = "correct"
            return res

        if s["phase"] == "main":
            s["phase"] = "hint_retry"
            # Busca otro problema del mismo nivel para usarlo como ejemplo resuelto de pista
            similar = next((p for p in self.problems_by_island[s["island_id"]] if p["id"] != prob["id"]), prob)
            hint_msg = (
                f"Ejemplo resuelto similar: «{similar['text'][:180]}...» "
                f"La respuesta correcta era {similar.get('label')} ({similar.get('options', {}).get(similar.get('label'), '')}). "
                f"Aplica la misma lógica a tu problema."
            )
            return {
                "status": "retry_with_hint",
                "feedback": "incorrect",
                "hint": hint_msg,
                "problem": self._format_problem(prob)
            }

        s["failed_for_review"].append(prob)
        res = self._advance_level_queue()
        res["feedback"] = "incorrect_moved_to_review"
        return res

    def _complete_level(self, island_id, level_idx):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE island_progress SET completed = 1 WHERE island_id = ? AND level_idx = ?",
                (island_id, level_idx)
            )
            c = conn.execute(
                "SELECT COUNT(*) as c FROM island_progress WHERE island_id = ? AND completed = 1",
                (island_id,)
            ).fetchone()["c"]

            if (c / LEVELS_PER_ISLAND) >= 0.8:
                prof = conn.execute("SELECT unlocked_accessories FROM profile WHERE id = 1").fetchone()
                accs = json.loads(prof["unlocked_accessories"])
                acc_name = ISLANDS_META[island_id]["accessory"]
                if acc_name not in accs:
                    accs.append(acc_name)
                    conn.execute(
                        "UPDATE profile SET unlocked_accessories = ? WHERE id = 1",
                        (json.dumps(accs),)
                    )
                    return {"unlocked": True, "accessory": acc_name, "island": ISLANDS_META[island_id]["name"]}
        return {"unlocked": False}

    def get_full_state(self):
        with self._get_conn() as conn:
            prof = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
            rows = conn.execute("SELECT * FROM island_progress").fetchall()

        islands = []
        for meta in ISLANDS_META:
            i = meta["id"]
            lvls = [r["completed"] for r in rows if r["island_id"] == i]
            pct = int((sum(lvls) / LEVELS_PER_ISLAND) * 100)
            islands.append({**meta, "levels": lvls, "completion_pct": pct, "island_completed": pct >= 80})

        return {
            "placement_done": bool(prof["placement_done"]),
            "assigned_island": prof["assigned_island"],
            "unlocked_accessories": json.loads(prof["unlocked_accessories"]),
            "islands": islands
        }

    def reset_profile(self):
        with self._get_conn() as conn:
            conn.execute("UPDATE profile SET placement_done = 0, assigned_island = 0, unlocked_accessories = '[]' WHERE id = 1")
            conn.execute("UPDATE island_progress SET completed = 0")
        self.active_session = None
        return self.get_full_state()