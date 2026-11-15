"""RAG sobre M3Kang: índice local de problemas resueltos (SQLite + coseno).

El backend anterior volvía a pedir 16 embeddings cada vez que el alumno fallaba
un problema; en la placa eso son segundos. Aquí el índice se construye **una
vez** (`main.py --build-index`) y una búsqueda es aritmética local: milisegundos.

Regla del repo de la Datathon que se respeta aquí: solo se indexan problemas de
entreno, y `exclude_id` descarta el problema que se está respondiendo **en todos
los idiomas**.
"""
import json
import os
import sqlite3
import time

from . import embed, problems as problems_mod

SCHEMA = """
CREATE TABLE IF NOT EXISTS problems (
    key TEXT PRIMARY KEY,
    id TEXT NOT NULL,
    language TEXT NOT NULL,
    level INTEGER NOT NULL,
    text TEXT NOT NULL,
    options TEXT NOT NULL,
    label TEXT NOT NULL,
    vector BLOB NOT NULL
)
"""


def count(path):
    """Cuántos problemas hay en el índice, sin cargar los vectores."""
    if not os.path.exists(path):
        return 0
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM problems").fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def build(path, items, languages=None, log=None, sleep=0.0):
    """Crea el índice desde cero. Devuelve cuántos problemas ha indexado.

    `items`: problemas ya resueltos (con `label`). `languages`: si se indica,
    solo se indexan esos idiomas (bge-small es un modelo inglés).
    """
    todo = [item for item in items if item.get("label")]
    if languages:
        wanted = set(languages)
        todo = [item for item in todo if item.get("language") in wanted]
    if not todo:
        raise ValueError("no hay problemas con respuesta para indexar")

    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    if os.path.exists(path):
        os.remove(path)

    conn = sqlite3.connect(path)
    try:
        conn.execute(SCHEMA)
        done = 0
        batch_size = 16
        for start in range(0, len(todo), batch_size):
            chunk = todo[start:start + batch_size]
            vectors = embed.embed([item["text"] for item in chunk])
            conn.executemany(
                "INSERT OR REPLACE INTO problems "
                "(key, id, language, level, text, options, label, vector) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        problems_mod.key_of(item),
                        item["id"],
                        item["language"],
                        int(item["level"]),
                        item["text"],
                        json.dumps(item["options"], ensure_ascii=False),
                        item["label"],
                        embed.pack(vector),
                    )
                    for item, vector in zip(chunk, vectors)
                ],
            )
            conn.commit()
            done += len(chunk)
            if log:
                log("  indexados {}/{}".format(done, len(todo)))
            if sleep:
                time.sleep(sleep)
        return done
    finally:
        conn.close()


class Index:
    """Búsqueda de problemas parecidos ya resueltos."""

    def __init__(self, path):
        self.path = path
        self.rows = []          # [(key, problema, vector)]
        self.dimension = 0
        if os.path.exists(path):
            self._load()

    def _load(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            records = conn.execute(
                "SELECT key, id, language, level, text, options, label, vector FROM problems"
            ).fetchall()
        finally:
            conn.close()
        for record in records:
            vector = embed.unpack(record["vector"])
            self.dimension = self.dimension or len(vector)
            if len(vector) != self.dimension:
                continue
            self.rows.append((record["key"], self._problem(record), vector))

    @staticmethod
    def _problem(record):
        return {
            "id": record["id"],
            "language": record["language"],
            "level": int(record["level"]),
            "text": record["text"],
            "options": json.loads(record["options"] or "{}"),
            "label": record["label"],
        }

    def __len__(self):
        return len(self.rows)

    def search(self, problem, k=3, exclude_id=None):
        """`[(score, problema)]`, mejor primero. Vacío si no hay índice."""
        if not self.rows:
            return []
        vector = embed.embed([problem["text"]], query=True)[0]
        scored = []
        for _, candidate, candidate_vector in self.rows:
            if exclude_id is not None and candidate["id"] == exclude_id:
                continue
            scored.append((embed.cosine(vector, candidate_vector), candidate))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[:max(1, int(k))]

    def similar_easier(self, problem, k=3):
        """Un ejemplo parecido y **más fácil** (nivel menor), si lo hay.

        Es el primer peldaño de la escalera de pistas: el alumno ve un problema
        parecido ya resuelto, de nivel igual o inferior al suyo.
        """
        hits = self.search(problem, k=max(k * 4, 8), exclude_id=problem.get("id"))
        if not hits:
            return []
        level = int(problem.get("level", 0))
        easier = [hit for hit in hits if hit[1]["level"] < level]
        return (easier or hits)[:max(1, int(k))]
