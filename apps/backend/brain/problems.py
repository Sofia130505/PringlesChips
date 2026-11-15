"""Lectura de problemas de M3Kang (`data/*.jsonl`).

Formato de una línea, tal como lo entrega el dataset:

    {"id": "lvl-0_2015_13", "language": "eng", "level": 0, "text": "...",
     "options": {"A": "12", "B": "15", "C": "18", "D": "20", "E": "24"}, "label": "C"}

`options` puede ser `{}` cuando el OCR no pudo leer cinco opciones de texto.
M3Kang es solo para investigación: `data/train.jsonl`, `data/val.jsonl`,
`data/images/` y `data/index.db` no se suben al repositorio.
"""
import json
import os

SOURCE_FILES = ("train.jsonl", "val.jsonl", "sample_problems.jsonl")
LETTERS = "ABCDE"


def _normalize(problem):
    """Deja el problema con los campos que usa el resto del cerebro."""
    options = {letter: str(problem["options"][letter]).strip()
               for letter in LETTERS
               if (problem.get("options") or {}).get(letter) not in (None, "")}
    label = str(problem.get("label") or "").strip().upper()
    return {
        "id": str(problem.get("id", "")),
        "language": str(problem.get("language", "eng")),
        "level": int(problem.get("level", 0) or 0),
        "year": problem.get("year"),
        "text": str(problem.get("text", "")).strip(),
        "options": options,
        "label": label if label in LETTERS else "",
    }


def load(path):
    """Lee un `.jsonl` y devuelve problemas normalizados, sin los niveles fuera de 0-7."""
    problems = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                problem = _normalize(json.loads(line))
            except (ValueError, TypeError):
                continue
            if 0 <= problem["level"] <= 7:
                problems.append(problem)
    return problems


def load_all(data_dir):
    """Carga los problemas agrupados por nivel.

    Devuelve `{"by_level": {0: [...], ...}, "files": [...], "total": n}`.
    Usa `train.jsonl` y `val.jsonl` si existen (el dataset completo) y, si no,
    cae a `sample_problems.jsonl` (los 5 problemas de ejemplo del repositorio).
    """
    by_level = {level: [] for level in range(8)}
    used = []

    for name in SOURCE_FILES:
        path = os.path.join(data_dir, name)
        if not os.path.exists(path):
            continue
        problems = load(path)
        if not problems:
            continue
        for problem in problems:
            by_level[problem["level"]].append(problem)
        used.append({"file": name, "count": len(problems)})
        # `train.jsonl`/`val.jsonl` son el dataset completo: no mezclar con el sample.
        if name in ("train.jsonl", "val.jsonl"):
            break

    total = sum(len(items) for items in by_level.values())
    return {"by_level": by_level, "files": used, "total": total}


def index_source(data_dir):
    """Problemas que pueden entrar en el índice RAG: **solo entreno, nunca validación**.

    Indexar `val.jsonl` haría que la puntuación del test oculto fuera mentira.
    Devuelve `(problemas, nombre_del_fichero)`.
    """
    train = os.path.join(data_dir, "train.jsonl")
    if os.path.exists(train):
        return load(train), "train.jsonl"
    sample = os.path.join(data_dir, "sample_problems.jsonl")
    if os.path.exists(sample):
        return load(sample), "sample_problems.jsonl"
    return [], ""


def key_of(problem):
    """Clave única: el mismo `id` existe traducido a varios idiomas."""
    return "{}|{}".format(problem["id"], problem.get("language", "eng"))


def available_levels(by_level):
    """Niveles que tienen al menos un problema."""
    return [level for level, items in sorted(by_level.items()) if items]


def option_lines(problem):
    """`A) 12` en varias líneas, para pintarlo en una consola o en una página."""
    return ["{}) {}".format(letter, problem["options"][letter])
            for letter in LETTERS if problem["options"].get(letter)]


def public(problem):
    """El problema sin su respuesta, para que el alumno no la vea."""
    shown = dict(problem)
    shown.pop("label", None)
    return shown


def image_name(problem):
    """Nombre del PNG del enunciado, si `prepare_m3kang.py --save-images` lo dejó."""
    return "{}_{}.png".format(problem["id"], problem.get("language", "eng"))


def image_path(data_dir, problem):
    """Ruta del PNG del enunciado o "" si no existe."""
    path = os.path.join(data_dir, "images", image_name(problem))
    return path if os.path.exists(path) else ""
