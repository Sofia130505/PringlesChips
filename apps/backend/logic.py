import json
import math
import os
import random
import sqlite3
import urllib.request

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


def _cosine_sim(v1, v2):
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    return dot / (norm1 * norm2) if norm1 and norm2 else 0.0


def _get_embedding(text):
    """Pide el vector de 384 dimensiones a bge-small en el Arduino (puerto 8082)."""
    req = urllib.request.Request(
        "http://127.0.0.1:8082/v1/embeddings",
        data=json.dumps({"input": text[:500]}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read().decode("utf-8"))["data"][0]["embedding"]


def find_similar_problem(target_prob, candidates):
    """Busca el problema más parecido usando embeddings del Arduino (con fallback en portátil)."""
    others = [p for p in candidates if p["id"] != target_prob["id"]]
    if not others:
        return target_prob

    try:
        target_vec = _get_embedding(target_prob["text"])
        best_prob, best_score = others[0], -1.0
        for cand in others[:15]:
            score = _cosine_sim(target_vec, _get_embedding(cand["text"]))
            if score > best_score:
                best_score, best_prob = score, cand
        return best_prob
    except Exception:
        words = set(w.lower() for w in target_prob["text"].split() if len(w) > 3)
        return max(
            others,
            key=lambda p: len(words.intersection(w.lower() for w in p["text"].split())),
            default=others[0],
        )


def generate_pedagogical_hint(problem, similar_prob):
    """Genera una pista pedagógica en el Arduino (puerto 8081) sin revelar la solución."""
    sim_label = similar_prob.get("label", "")
    sim_val = (similar_prob.get("options") or {}).get(sim_label, "")
    prompt = (
        f"Eres un tutor de matemáticas para niños. El alumno falló este problema: '{problem['text']}'. "
        f"Aquí tienes un problema parecido ya resuelto: '{similar_prob['text']}' cuya respuesta correcta es {sim_label} ({sim_val}). "
        f"Explica en 2 frases cortas cómo se resuelve el ejemplo parecido para darle una pista, SIN decir la respuesta del problema del alumno."
    )
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8081/v1/chat/completions",
            data=json.dumps({
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 70,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            hint = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"].strip()
            correct_val = str((problem.get("options") or {}).get(problem.get("label"), ""))
            if correct_val and len(correct_val) > 1 and correct_val in hint:
                raise ValueError("Spoiler detectado")
            return hint
    except Exception:
        return (
            f"Fíjate en este problema parecido: «{similar_prob['text'][:160]}...» "
            f"Su respuesta correcta era {sim_label} ({sim_val}). Usa esa misma estrategia para resolver el tuyo."
        )


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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS attempt_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    island_id INTEGER,
                    problem_id TEXT,
                    phase TEXT,
                    is_correct INTEGER,
                    used_dont_know INTEGER
                )
            """)
            conn.execute("INSERT OR IGNORE INTO profile (id) VALUES (1)")
            for i in range(8):
                for lvl in range(LEVELS_PER_ISLAND):
                    conn.execute(
                        "INSERT OR IGNORE INTO island_progress (island_id, level_idx, completed) VALUES (?, ?, 0)",
                        (i, lvl),
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
            "image_url": img_url,
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
            "current_problem": None,
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
            "problem": self._format_problem(prob),
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
                    (assigned,),
                )
            self.active_session = None
            return {
                "status": "finished",
                "assigned_island": assigned,
                "island_info": ISLANDS_META[assigned],
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
            "current_problem": None,
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
                "problem": self._format_problem(s["current_problem"]),
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
                "message": "No acertaste todos en el repaso final. ¡Vuelve a intentarlo!",
            }

        reward = self._complete_level(s["island_id"], s["level_idx"])
        self.active_session = None
        return {"status": "level_completed", "reward": reward}

    def submit_level_answer(self, answer):
        s = self.active_session
        if not s or s["mode"] != "level":
            return {"error": "No hay nivel activo"}

        prob = s["current_problem"]
        is_correct = (answer == prob.get("label"))

        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO attempt_logs (island_id, problem_id, phase, is_correct, used_dont_know) VALUES (?, ?, ?, ?, ?)",
                (s["island_id"], prob["id"], s["phase"], int(is_correct), int(answer == "DONT_KNOW")),
            )

        if is_correct:
            res = self._advance_level_queue()
            res["feedback"] = "correct"
            return res

        if s["phase"] == "main":
            s["phase"] = "hint_retry"
            similar = find_similar_problem(prob, self.problems_by_island[s["island_id"]])
            hint_msg = generate_pedagogical_hint(prob, similar)
            return {
                "status": "retry_with_hint",
                "feedback": "incorrect",
                "hint": hint_msg,
                "similar_problem_id": similar["id"],
                "problem": self._format_problem(prob),
            }

        s["failed_for_review"].append(prob)
        res = self._advance_level_queue()
        res["feedback"] = "incorrect_moved_to_review"
        return res

    def _complete_level(self, island_id, level_idx):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE island_progress SET completed = 1 WHERE island_id = ? AND level_idx = ?",
                (island_id, level_idx),
            )
            c = conn.execute(
                "SELECT COUNT(*) as c FROM island_progress WHERE island_id = ? AND completed = 1",
                (island_id,),
            ).fetchone()["c"]

            if (c / LEVELS_PER_ISLAND) >= 0.8:
                prof = conn.execute("SELECT unlocked_accessories FROM profile WHERE id = 1").fetchone()
                accs = json.loads(prof["unlocked_accessories"])
                acc_name = ISLANDS_META[island_id]["accessory"]
                if acc_name not in accs:
                    accs.append(acc_name)
                    conn.execute(
                        "UPDATE profile SET unlocked_accessories = ? WHERE id = 1",
                        (json.dumps(accs),),
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
            "islands": islands,
        }

    def get_analytics(self):
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT island_id,
                       COUNT(*) as total_attempts,
                       SUM(is_correct) as correct_count,
                       SUM(used_dont_know) as dont_know_count
                FROM attempt_logs
                GROUP BY island_id
            """).fetchall()
        return [dict(r) for r in rows]

    def reset_profile(self):
        with self._get_conn() as conn:
            conn.execute("UPDATE profile SET placement_done = 0, assigned_island = 0, unlocked_accessories = '[]' WHERE id = 1")
            conn.execute("UPDATE island_progress SET completed = 0")
            conn.execute("DELETE FROM attempt_logs")
        self.active_session = None
        return self.get_full_state()