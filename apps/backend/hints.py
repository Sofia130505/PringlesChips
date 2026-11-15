"""Pista conceptual del modelo local (llama.cpp en el puerto 8081).

La forma se fuerza con una gramática: una apertura, hasta 15 palabras y un punto.
Los dígitos están prohibidos, así que la pista no puede contener el valor de
ninguna opción. La pista sale en el idioma del enunciado.
"""
from __future__ import annotations

import json
import re
import urllib.request
import zlib
from collections import Counter

LLM_URL = "http://127.0.0.1:8081/v1/chat/completions"
TIMEOUT = 30.0

HINT_SYSTEM = (
    "You are a maths tutor for school students. Give one conceptual hint, at most 15 words. "
    "Say what to compare, count, or split apart, never the final value. No numbers, no answer."
)

LANGUAGE_NAMES = {"cat": "Catalan", "eng": "English", "spa": "Spanish"}
OPENERS = {
    "cat": ("Compara", "Relaciona"),
    "eng": ("Compare", "Relate"),
    "spa": ("Compara", "Relaciona"),
}

# Palabras vacías: no cuentan para detectar una pista degenerada.
FUNCTION_WORDS = {
    "the", "a", "an", "of", "to", "in", "on", "at", "by", "for", "and", "or", "with",
    "that", "this", "as", "is", "are", "be", "it", "its", "from", "into", "i", "els",
    "les", "de", "del", "dels", "amb", "que", "per", "la", "el",
}


def _grammar(opener):
    return ('root ::= "' + opener + '" " " phrase "."\n'
            'phrase ::= word (" " word){0,14}\n'
            "word ::= [A-Za-zÀ-ÖØ-öø-ÿ·']+\n")


GRAMMARS = {opener: _grammar(opener) for openers in OPENERS.values() for opener in openers}


def openers_for(problem):
    """Aperturas del idioma del problema; inglés si no lo conocemos."""
    language = str(problem.get("language", "")).lower()
    return OPENERS.get(language, OPENERS["eng"])


def opener_for(problem):
    """Mismo problema, misma apertura; problemas vecinos alternan."""
    openers = openers_for(problem)
    return openers[zlib.crc32(str(problem.get("id", "")).encode()) % len(openers)]


def format_problem(problem):
    options = problem.get("options") or {}
    lines = [str(problem.get("text", "")).strip()]
    lines.extend(f"{letter}) {options[letter]}" for letter in "ABCDE" if letter in options)
    if not options:
        lines.append("(The options are in the picture.)")
    return "\n".join(lines)


def build_messages(problem):
    text = format_problem(problem)
    language = LANGUAGE_NAMES.get(str(problem.get("language", "")).lower())
    if language:
        text += f"\nWrite the hint in {language}."
    return [
        {"role": "system", "content": HINT_SYSTEM},
        {"role": "user", "content": text},
    ]


def _call(problem, opener, url, timeout):
    payload = {
        "messages": build_messages(problem),
        "max_tokens": 60,
        "temperature": 0,
        "grammar": GRAMMARS[opener],
        "stop": ["\n\n", "Answer:", "The answer is"],
        "cache_prompt": True,
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return (data["choices"][0]["message"].get("content") or "").strip()


def generate(problem, url=LLM_URL, timeout=TIMEOUT):
    """Devuelve la pista y sus comprobaciones. Lanza excepción si el modelo no contesta."""
    opener = opener_for(problem)
    order = [opener] + [other for other in openers_for(problem) if other != opener]
    text = ""
    for candidate in order:
        text = _call(problem, candidate, url, timeout)
        if not degenerate(text):
            break
    return {
        "text": text,
        "leaks": leaks(text, problem),
        "language_ok": language_ok(problem, text),
        "degenerate": degenerate(text),
    }


def leaks(text, problem):
    """¿La pista da la letra o el valor de la respuesta correcta?"""
    flags = []
    label = str(problem.get("label", "")).upper()
    value = str((problem.get("options") or {}).get(label, ""))
    if label and (re.search(rf"answer\s*(?:is|:)\s*\(?{label}\b", text.lower())
                  or re.search(rf"\b{label}\s*[).:]", text)):
        flags.append("nombra la letra")
    if value and re.search(rf"(?<![\d.,]){re.escape(value)}(?![\d.,])", text):
        flags.append("contiene el valor " + value)
    return flags


def degenerate(text):
    """Detecta salidas como 'icos i icos i icos'."""
    words = re.findall(r"[a-zà-ÿ']+", text.lower())
    if any(words[i] == words[i + 1] == words[i + 2] for i in range(max(0, len(words) - 2))):
        return True
    content = Counter(word for word in words if word not in FUNCTION_WORDS)
    return bool(content) and max(content.values()) >= 4


CAT_WORDS = {"el", "la", "els", "les", "del", "dels", "amb", "i", "que", "per", "un", "una",
             "és", "són", "cada", "nombre", "figura", "costat", "costats", "vèrtex", "vèrtexs",
             "arestes", "files", "columnes", "suma", "quadrat", "cercle", "mur", "tropes",
             "carreteres", "àrea", "perímetre", "dreta", "esquerra"}
ENG_WORDS = {"the", "with", "and", "to", "in", "each", "between", "is", "are", "its", "their",
             "this", "that", "from", "how", "many", "number", "numbers", "cells", "cell",
             "area", "perimeter", "side", "sides", "row", "column", "edge", "edges", "sum"}


def detect_language(text):
    """Clasificador aproximado catalán/inglés; cadena vacía si hay poca evidencia."""
    low = text.lower()
    words = re.findall(r"[a-zà-ÿ·']+", low)
    cat = sum(1 for word in words if word in CAT_WORDS) + (1 if re.search(r"[àèìòùçï·]", low) else 0)
    eng = sum(1 for word in words if word in ENG_WORDS)
    if cat >= 2 and cat > eng:
        return "cat"
    if eng >= 2 and eng > cat:
        return "eng"
    return ""


def language_ok(problem, text):
    """True/False cuando se puede decidir, None si la pista es demasiado corta."""
    detected = detect_language(text)
    if not detected:
        return None
    return detected == str(problem.get("language", "")).lower()
