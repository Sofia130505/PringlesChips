"""Cliente HTTP mínimo para hablar con los servidores llama.cpp de la placa.

Solo `urllib` (librería estándar), como pide el repositorio de la Datathon:
nada de `requests`, nada de red externa, todo contra 127.0.0.1.
"""
import json
import urllib.error
import urllib.request


class ServiceError(RuntimeError):
    """El servidor no contesta, contesta lento o contesta algo que no es JSON."""


def _request(url, data=None, timeout=30):
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        raise ServiceError("{} -> HTTP {}: {}".format(url, error.code, detail)) from error
    except (urllib.error.URLError, OSError) as error:
        raise ServiceError("{} -> {}".format(url, error)) from error

    if not body:
        return {}
    try:
        return json.loads(body)
    except ValueError as error:
        raise ServiceError("{} -> respuesta no JSON: {!r}".format(url, body[:120])) from error


def get(url, timeout=5):
    """GET que devuelve el JSON ya parseado."""
    return _request(url, data=None, timeout=timeout)


def post(url, payload, timeout=30):
    """POST con cuerpo JSON que devuelve el JSON ya parseado."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return _request(url, data=body, timeout=timeout)


def health(url, timeout=3):
    """`/health` de llama.cpp: `{"status": "ok"}`. True si está listo."""
    try:
        return get(url.rstrip("/") + "/health", timeout=timeout).get("status") == "ok"
    except ServiceError:
        return False
