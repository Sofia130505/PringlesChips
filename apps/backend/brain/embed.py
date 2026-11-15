"""Embeddings con bge-small-en-v1.5 (servidor llama.cpp en el puerto 8082).

Detalle que importa (lo dice el repo de la Datathon): bge-small es un modelo
inglés y las **consultas** llevan un prefijo, los **documentos** guardados en el
índice no. Guardamos los vectores ya normalizados, así la similitud es un
producto escalar y buscar en el índice no necesita `math.sqrt` por candidato.
"""
import array
import math

from . import client, config


def _normalize(vector):
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return list(vector)
    return [value / norm for value in vector]


def embed(texts, query=False, timeout=None):
    """Devuelve un vector normalizado (lista de floats) por cada texto."""
    texts = [text if isinstance(text, str) else str(text) for text in texts]
    if not texts:
        return []

    prefix = config.CONFIG["EMBED_QUERY_PREFIX"] if query else ""
    url = config.base_url("EMBED") + "/v1/embeddings"
    wait = timeout if timeout is not None else config.number("EMBED_TIMEOUT")
    batch_size = max(1, config.number("EMBED_BATCH"))

    vectors = []
    for start in range(0, len(texts), batch_size):
        chunk = [prefix + text for text in texts[start:start + batch_size]]
        data = client.post(url, {"input": chunk}, timeout=wait)
        rows = data.get("data") or []
        if len(rows) != len(chunk):
            raise client.ServiceError(
                "embeddings: pedí {} textos y llegaron {} vectores".format(len(chunk), len(rows))
            )
        rows = sorted(rows, key=lambda row: row.get("index", 0))
        vectors.extend(_normalize(row["embedding"]) for row in rows)
    return vectors


def cosine(left, right):
    """Similitud coseno. Si ambos vectores están normalizados es su producto escalar."""
    return sum(a * b for a, b in zip(left, right))


def pack(vector):
    """Vector -> bytes para guardarlo en SQLite (`float32`, 4 bytes por dimensión)."""
    return array.array("f", vector).tobytes()


def unpack(blob):
    """bytes de SQLite -> lista de floats."""
    values = array.array("f")
    values.frombytes(blob)
    return list(values)
