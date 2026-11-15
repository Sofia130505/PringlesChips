"""Ask the small language model for one letter, A to E."""
import re
import zlib
from collections import Counter

from .config import CONFIG
from .client import post

URL = f"http://127.0.0.1:{CONFIG['LLM_PORT']}/v1/chat/completions"

# Keep the system prompt stable: llama-server caches the start of the prompt,
# so text that never changes is only read once.
SYSTEM = ("You solve multiple-choice math competition problems for school students. "
          "Read the problem and the options, then reply with the letter of the correct option.")


def format_problem(problem, sees_image=False):
    lines = [problem["text"].strip()]
    options = problem.get("options") or {}
    for letter in "ABCDE":
        if letter in options:
            lines.append(f"{letter}) {options[letter]}")
    if not options:
        lines.append("(The options are in the picture.)" if sees_image else
                     "(The options are in a picture that you can't see. Pick the most likely letter.)")
    return "\n".join(lines)


def build_messages(problem, examples=(), image_b64=None):
    """image_b64 is a PNG as base64 text. Only a server started with --mmproj can see it."""
    messages = [{"role": "system", "content": SYSTEM}]
    for ex in examples:  # solved problems retrieved with RAG, if any
        messages.append({"role": "user", "content": format_problem(ex) + "\nAnswer:"})
        messages.append({"role": "assistant", "content": ex["label"]})
    text = format_problem(problem, sees_image=bool(image_b64)) + "\nAnswer:"
    if image_b64:
        content = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + image_b64}},
                   {"type": "text", "text": text}]
    else:
        content = text
    messages.append({"role": "user", "content": content})
    return messages


EXPLAIN_SYSTEM = ("You are a patient maths tutor for school students. Start with one short hint "
                  "that does not give the answer away, then solve the problem step by step. "
                  "The last line must be exactly 'FINAL: <letter>'.")

# Level 1 of the hint ladder: a conceptual nudge. Constant text so llama-server can cache it.
HINT_SYSTEM = ("You are a maths tutor for school students. Give one conceptual hint, at most 15 words. "
               "Say what to compare, count, or split apart, never the final value. No numbers, no answer.")

# The model is tuned to solve, so the shape is enforced: opener + <=15 words + full stop.
# Digits are banned by the grammar, which makes leaking an option value impossible.
# One opener per request, chosen from the problem id: letting the model choose makes it
# say "Compare" every single time, which reads as a stuck record in the UI.
# Openers are per language: the forced first word drags the rest of the sentence with it.
HINT_OPENERS = {
    "eng": ("Compare", "Relate"),
    "cat": ("Compara", "Relaciona"),
}

# ~5 extra user tokens; the system prompt stays identical, so its cache is untouched.
LANGUAGE_NAMES = {"eng": "English", "cat": "Catalan"}

CAT_WORDS = {"el", "la", "els", "les", "del", "dels", "amb", "i", "que", "per", "un", "una",
             "és", "són", "cada", "nombre", "figura", "costat", "costats", "vèrtex", "vèrtexs",
             "arestes", "files", "columnes", "suma", "quadrat", "cercle", "mur", "tropes",
             "carreteres", "àrea", "perímetre", "dreta", "esquerra"}
ENG_WORDS = {"the", "with", "and", "to", "in", "each", "between", "is", "are", "its", "their",
             "this", "that", "from", "how", "many", "number", "numbers", "cells", "cell",
             "area", "perimeter", "side", "sides", "row", "column", "edge", "edges", "sum"}


def detect_language(text):
    """Rough eng/cat classifier for one short hint. '' when the evidence is weak."""
    low = text.lower()
    words = re.findall(r"[a-zà-ÿ·']+", low)
    cat = sum(1 for w in words if w in CAT_WORDS) + (1 if re.search(r"[àèìòùçï·]", low) else 0)
    eng = sum(1 for w in words if w in ENG_WORDS)
    if cat >= 2 and cat > eng:
        return "cat"
    if eng >= 2 and eng > cat:
        return "eng"
    return ""


def language_ok(problem, text):
    """True/False when we can tell, None when the hint is too short to classify."""
    detected = detect_language(text)
    if not detected:
        return None
    return detected == problem.get("language", "")


def _hint_grammar(opener):
    return ('root ::= "' + opener + '" " " phrase "."\n'
            'phrase ::= word (" " word){0,14}\n'
            "word ::= [A-Za-zÀ-ÖØ-öø-ÿ·']+\n")


HINT_GRAMMARS = {opener: _hint_grammar(opener) for openers in HINT_OPENERS.values() for opener in openers}


def hint_openers(problem):
    """Openers for this problem's language; English is the fallback."""
    return HINT_OPENERS.get(problem.get("language", ""), HINT_OPENERS["eng"])


def hint_opener(problem):
    """Same problem -> same opener, neighbouring problems differ."""
    openers = hint_openers(problem)
    return openers[zlib.crc32(problem.get("id", "").encode()) % len(openers)]


def build_hint_messages(problem, image_b64=None):
    """Same content as build_messages, but without the 'Answer:' suffix."""
    text = format_problem(problem, sees_image=bool(image_b64))
    language = LANGUAGE_NAMES.get(problem.get("language", ""))
    if language:
        text += f"\nWrite the hint in {language}."
    if image_b64:
        content = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + image_b64}},
                   {"type": "text", "text": text}]
    else:
        content = text
    return [{"role": "system", "content": HINT_SYSTEM},
            {"role": "user", "content": content}]


HINT_FUNCTION_WORDS = {"the", "a", "an", "of", "to", "in", "on", "at", "by", "for", "and", "or",
                       "with", "that", "this", "as", "is", "are", "be", "it", "its", "from",
                       "into", "i", "els", "les", "de", "del", "dels", "amb", "que", "per"}


def hint_degenerate(text):
    """Catch grammar-valid nonsense like 'Compare the digits with icos i icos i icos i'."""
    words = re.findall(r"[a-zà-ÿ']+", text.lower())
    if any(words[i] == words[i + 1] == words[i + 2] for i in range(max(0, len(words) - 2))):
        return True
    content = Counter(w for w in words if w not in HINT_FUNCTION_WORDS)
    return bool(content) and max(content.values()) >= 4


def hint(problem, image_b64=None, url=URL, timeout=60, max_tokens=60):
    """Return (hint text, timings). Free text, but capped and hard-stopped.

    A degenerate hint is retried once with the other opener: temperature 0 makes a
    repeat request on the same grammar return the same nonsense.
    """
    opener = hint_opener(problem)
    order = [opener] + [o for o in hint_openers(problem) if o != opener]
    text, timings = "", {}
    for attempt in order:
        response = post(url, {
            "messages": build_hint_messages(problem, image_b64),
            "max_tokens": max_tokens,
            "temperature": 0,
            "grammar": HINT_GRAMMARS[attempt],
            "stop": ["\n\n", "Answer:", "The answer is"],
            "cache_prompt": True,
        }, timeout=timeout)
        text = (response["choices"][0]["message"].get("content") or "").strip()
        timings = response.get("timings", {})
        if not hint_degenerate(text):
            break
    return text, timings


def hint_leaks(text, problem):
    """Cheap guardrail: does the hint give away the letter or the correct value?"""
    flags = []
    label = problem.get("label") or ""
    value = (problem.get("options") or {}).get(label, "")
    low = text.lower()
    if re.search(rf"answer\s*(?:is|:)\s*\(?{label}\b", low) or re.search(rf"\b{label}\s*[).:]", text):
        flags.append("names the answer letter")
    if value and re.search(rf"(?<![\d.,]){re.escape(str(value))}(?![\d.,])", text):
        flags.append(f"contains the option value {value}")
    return flags


def explain_messages(problem, image_b64=None):
    """Free-form prompt: hint, reasoning, final letter. No grammar, so the model can talk."""
    text = format_problem(problem, sees_image=bool(image_b64))
    if image_b64:
        content = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + image_b64}},
                   {"type": "text", "text": text}]
    else:
        content = text
    return [{"role": "system", "content": EXPLAIN_SYSTEM},
            {"role": "user", "content": content}]


def explain(problem, image_b64=None, url=URL, timeout=300, max_tokens=400):
    """Return (reply text, letter parsed from the last line or "")."""
    response = post(url, {
        "messages": explain_messages(problem, image_b64),
        "max_tokens": max_tokens,
        "temperature": 0,
        "cache_prompt": True,
    }, timeout=timeout)
    reply = (response["choices"][0]["message"].get("content") or "").strip()
    return reply, parse_letter(reply)


def parse_letter(reply):
    """Accept 'FINAL: C', '**Final:** C' on its own line, or a bare 'C)' near the end."""
    match = re.search(r"(?:FINAL|Final|ANSWER|Answer)\s*[:\-]*\s*\**\s*\(?([A-E])\b", reply)
    if match:
        return match.group(1)
    tail = re.findall(r"\(?([A-E])\)?\s*[).:]", reply[-200:])
    return tail[-1] if tail else ""


def answer_letter(problem, examples=(), timeout=60, image_b64=None, url=URL):
    """Return (letter, timings). The grammar makes any other output impossible."""
    response = post(url, {
        "messages": build_messages(problem, examples, image_b64),
        "grammar": "root ::= [A-E]",
        "max_tokens": 1,
        "temperature": 0,
        "seed": int(CONFIG["SEED"]),
        "cache_prompt": True,
    }, timeout=timeout)
    letter = response["choices"][0]["message"]["content"].strip()
    return letter, response.get("timings", {})
