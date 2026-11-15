"""Llamadas al modelo de lenguaje (servidor llama.cpp en el puerto 8081).

Dos reglas del repo de la Datathon que este módulo respeta:

* El prompt del sistema es **estable** para que `cache_prompt` reaproveche el
  principio del prompt (la placa lee a ~11 tokens por segundo).
* Para elegir la respuesta se usa la gramática `root ::= [A-E]` con
  `max_tokens: 1`: el modelo no puede escribir nada que no sea una letra.

Ninguna de estas funciones debe llamarse desde un handler HTTP: tardan entre
5 y 30 segundos en la placa. El servidor web las lanza en un hilo.
"""
from . import client, config

LETTER_GRAMMAR = "root ::= [A-E]"
SYSTEM = (
    "You are a maths tutor for the Kangaroo competition. "
    "Read the problem and reply with exactly one letter: A, B, C, D or E."
)
HINT_SYSTEM = (
    "Eres un tutor de matematicas para ninos de primaria. "
    "Explicas la estrategia en dos frases cortas y nunca dices la respuesta."
)


def health(timeout=None):
    """True si el servidor del modelo contesta `/health`."""
    return client.health(
        config.base_url("LLM"),
        timeout=timeout if timeout is not None else config.number("HEALTH_TIMEOUT"),
    )


def chat(messages, max_tokens=64, temperature=0.0, grammar=None, timeout=None):
    """Una `chat/completions` contra el modelo. Devuelve el texto de la respuesta."""
    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "seed": config.number("SEED"),
        "cache_prompt": True,
    }
    if grammar:
        payload["grammar"] = grammar

    url = config.base_url("LLM") + "/v1/chat/completions"
    wait = timeout if timeout is not None else config.number("LLM_TIMEOUT")
    data = client.post(url, payload, timeout=wait)
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError) as error:
        raise client.ServiceError("respuesta inesperada del modelo: {!r}".format(data)[:300]) from error


def format_problem(problem):
    """Enunciado en una sola línea compacta: menos tokens, menos segundos."""
    text = " ".join(str(problem.get("text", "")).split())
    options = problem.get("options") or {}
    parts = ["{}: {}".format(letter, options[letter]) for letter in "ABCDE" if options.get(letter)]
    if parts:
        text += " | " + " | ".join(parts)
    return text


def build_messages(problem, examples=()):
    """Mensajes para pedir una letra. `examples`: problemas ya resueltos (RAG)."""
    blocks = []
    if examples:
        solved = ["{} -> {}".format(format_problem(item), item.get("label", "")) for item in examples]
        blocks.append("Solved examples:\n" + "\n".join(solved))
    blocks.append("Problem: " + format_problem(problem))
    blocks.append("Answer with one letter.")
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]


def answer_letter(problem, examples=(), timeout=None):
    """Una letra de la A a la E para el problema, forzada por gramática."""
    messages = build_messages(problem, examples)
    text = chat(messages, max_tokens=1, grammar=LETTER_GRAMMAR, timeout=timeout)
    letter = text[:1].upper()
    if letter not in "ABCDE":
        raise client.ServiceError("el modelo no devolvió una letra: {!r}".format(text))
    return letter


def build_hint_messages(problem, example):
    """Mensajes para la pista pedagógica, con un problema parecido ya resuelto."""
    example_label = example.get("label", "")
    example_value = (example.get("options") or {}).get(example_label, "")
    prompt = (
        "El alumno ha fallado este problema: '{problem}'.\n"
        "Un problema parecido ya resuelto: '{example}' con respuesta correcta {label} ({value}).\n"
        "Explica en dos frases cortas como se resuelve el ejemplo parecido, para darle una pista. "
        "No digas la respuesta del problema del alumno."
    ).format(
        problem=format_problem(problem),
        example=format_problem(example),
        label=example_label,
        value=example_value,
    )
    return [
        {"role": "system", "content": HINT_SYSTEM},
        {"role": "user", "content": prompt},
    ]


def hint(problem, example, max_tokens=70, timeout=None):
    """Pista corta del modelo. Lanza `ServiceError` si no contesta."""
    messages = build_hint_messages(problem, example)
    return chat(messages, max_tokens=max_tokens, timeout=timeout)
