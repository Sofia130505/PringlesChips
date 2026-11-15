"""Todo lo que el alumno deja guardado, en SQLite (sin dependencias).

Se reutiliza **el mismo esquema y el mismo archivo** que ya usaba el backend
anterior (`data/game_state.db`), así no se pierde el progreso y el compañero
que monte el servidor web puede leer las tablas tal cual:

    profile         una fila (id = 1): test hecho, isla asignada, accesorios
    island_progress 8 islas x 5 niveles, con `completed` en 0 o 1
    attempt_logs    un registro por respuesta, para las estadísticas
"""
import json
import os
import sqlite3

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS profile (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        placement_done INTEGER DEFAULT 0,
        assigned_island INTEGER DEFAULT 0,
        unlocked_accessories TEXT DEFAULT '[]'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS island_progress (
        island_id INTEGER,
        level_idx INTEGER,
        completed INTEGER DEFAULT 0,
        PRIMARY KEY (island_id, level_idx)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attempt_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        island_id INTEGER,
        problem_id TEXT,
        phase TEXT,
        is_correct INTEGER,
        used_dont_know INTEGER
    )
    """,
)


class Store:
    """Perfil, progreso e intentos del alumno."""

    def __init__(self, path, islands=8, levels_per_island=5):
        self.path = path
        self.islands = islands
        self.levels_per_island = levels_per_island
        folder = os.path.dirname(os.path.abspath(path))
        if folder:
            os.makedirs(folder, exist_ok=True)
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._conn() as conn:
            for statement in SCHEMA:
                conn.execute(statement)
            conn.execute("INSERT OR IGNORE INTO profile (id) VALUES (1)")
            for island_id in range(self.islands):
                for level_idx in range(self.levels_per_island):
                    conn.execute(
                        "INSERT OR IGNORE INTO island_progress (island_id, level_idx, completed) "
                        "VALUES (?, ?, 0)",
                        (island_id, level_idx),
                    )

    # --- perfil ---
    def profile(self):
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
        return {
            "placement_done": bool(row["placement_done"]),
            "assigned_island": int(row["assigned_island"]),
            "unlocked_accessories": json.loads(row["unlocked_accessories"] or "[]"),
        }

    def set_placement(self, assigned_island):
        with self._conn() as conn:
            conn.execute(
                "UPDATE profile SET placement_done = 1, assigned_island = ? WHERE id = 1",
                (int(assigned_island),),
            )

    def add_accessory(self, name):
        """Añade un accesorio si no estaba. True si es nuevo."""
        accessories = self.profile()["unlocked_accessories"]
        if name in accessories:
            return False
        accessories.append(name)
        with self._conn() as conn:
            conn.execute(
                "UPDATE profile SET unlocked_accessories = ? WHERE id = 1",
                (json.dumps(accessories, ensure_ascii=False),),
            )
        return True

    # --- progreso ---
    def levels(self, island_id):
        """Lista de 0/1 por `level_idx` de una isla."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT level_idx, completed FROM island_progress "
                "WHERE island_id = ? ORDER BY level_idx",
                (int(island_id),),
            ).fetchall()
        done = [0] * self.levels_per_island
        for row in rows:
            if 0 <= row["level_idx"] < self.levels_per_island:
                done[row["level_idx"]] = int(row["completed"])
        return done

    def complete_level(self, island_id, level_idx):
        """Marca el nivel como superado y devuelve cuántos van en esa isla."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE island_progress SET completed = 1 WHERE island_id = ? AND level_idx = ?",
                (int(island_id), int(level_idx)),
            )
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM island_progress WHERE island_id = ? AND completed = 1",
                (int(island_id),),
            ).fetchone()["c"]
        return int(count)

    # --- intentos ---
    def add_attempt(self, island_id, problem_id, phase, is_correct, used_dont_know):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO attempt_logs "
                "(island_id, problem_id, phase, is_correct, used_dont_know) "
                "VALUES (?, ?, ?, ?, ?)",
                (int(island_id), str(problem_id), str(phase),
                 int(bool(is_correct)), int(bool(used_dont_know))),
            )

    def analytics(self):
        """Aciertos y fallos por isla, para la pantalla de estadísticas."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT island_id, COUNT(*) AS total_attempts, "
                "SUM(is_correct) AS correct_count, SUM(used_dont_know) AS dont_know_count "
                "FROM attempt_logs GROUP BY island_id ORDER BY island_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def reset(self):
        """Borra todo el progreso (botón "reiniciar" del mapa)."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE profile SET placement_done = 0, assigned_island = 0, "
                "unlocked_accessories = '[]' WHERE id = 1"
            )
            conn.execute("UPDATE island_progress SET completed = 0")
            conn.execute("DELETE FROM attempt_logs")
