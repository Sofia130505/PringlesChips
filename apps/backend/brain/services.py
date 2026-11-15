"""Comprobación de los servicios que corren fuera de la app (la placa).

| Servicio | Puerto | Modelo                                   | Unidad systemd |
|----------|--------|------------------------------------------|----------------|
| LLM      | 8081   | Qwen3.5 0.8B Q8_0                        | `math-llm`     |
| Embed    | 8082   | bge-small-en-v1.5 Q8_0 (384 dimensiones) | `math-embed`   |
| Vision   | 8083   | opcional, a mano                         | ninguna        |

Los tres escuchan solo en 127.0.0.1. Comprobarlos al arrancar evita el fallo
más típico de la placa: seguir adelante sin modelo y morir 30 s más tarde.
"""
import time

from . import client, config

REQUIRED = ("LLM", "EMBED")
OPTIONAL = ("VISION",)
LABELS = {
    "LLM": "modelo de lenguaje (Qwen3.5 0.8B)",
    "EMBED": "embeddings (bge-small-en-v1.5)",
    "VISION": "visión (opcional)",
}


def check(name, timeout=None):
    """Estado de un servicio: `{"service", "url", "up", "error"}`."""
    url = config.base_url(name)
    wait = timeout if timeout is not None else config.number("HEALTH_TIMEOUT")
    result = {"service": name, "label": LABELS.get(name, name), "url": url,
              "up": False, "error": "", "required": name in REQUIRED}
    try:
        payload = client.get(url + "/health", timeout=wait)
    except client.ServiceError as error:
        result["error"] = str(error)
        return result
    result["up"] = payload.get("status") == "ok"
    if not result["up"]:
        result["error"] = "status = {!r}".format(payload.get("status"))
    return result


def status(timeout=None):
    """Estado de LLM + embeddings + visión. `ok` = están los obligatorios."""
    services = {name: check(name, timeout) for name in REQUIRED + OPTIONAL}
    services["ok"] = all(services[name]["up"] for name in REQUIRED)
    return services


def reason(service):
    """Motivo corto del fallo, sin repetir la URL que ya se ha enseñado."""
    text = str(service.get("error") or "sin respuesta")
    return text.split(" -> ")[-1]


def report(services):
    """Líneas de texto con el estado, para la consola de `main.py`."""
    lines = []
    for name in REQUIRED + OPTIONAL:
        service = services[name]
        mark = "OK  " if service["up"] else "DOWN"
        suffix = "" if service["required"] else " (opcional)"
        lines.append("  [{}] {:<34}{}{}".format(mark, service["label"], service["url"], suffix))
        if not service["up"]:
            lines.append("         motivo: " + reason(service))
    return lines


def wait(timeout=60, interval=3):
    """Espera (hasta `timeout` segundos) a que los servicios obligatorios suban."""
    deadline = time.time() + timeout
    while True:
        services = status()
        if services["ok"] or time.time() >= deadline:
            return services
        time.sleep(interval)
