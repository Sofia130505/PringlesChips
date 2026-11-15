#!/usr/bin/env python3
"""Placa de mentira: imita los servidores llama.cpp para programar sin hardware.

    python scripts/fake_board.py                 # levanta 8081 (LLM) y 8082 (embeddings)
    python scripts/fake_board.py --llm-port 9081 --embed-port 9082

Endpoints que imita (los mismos que la placa de verdad):

    GET  /health               -> {"status": "ok"}
    POST /v1/embeddings        -> {"data": [{"embedding": [...384 floats...], "index": 0}]}
    POST /v1/chat/completions  -> con gramática devuelve "A"; sin gramática, una pista

Los vectores no son los de bge-small (ese modelo vive en la placa), pero son
deterministas y salen parecidos cuando dos textos comparten palabras: suficiente
para probar el índice RAG, las pistas y el servidor web sin la placa delante.
"""
import argparse
import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIM = 384
FAKE_HINT = "Multiplica los grupos y después quita los que se han gastado. Fíjate en el ejemplo parecido."


def embed_vector(text):
    """Bolsa de palabras con hash -> vector de 384 dimensiones, normalizado."""
    vector = [0.0] * DIM
    for word in re.findall(r"[a-z0-9]+", str(text).lower()):
        index = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16) % DIM
        vector[index] += 1.0
    norm = sum(value * value for value in vector) ** 0.5 or 1.0
    return [value / norm for value in vector]


def make_handler(role):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print("  [{}] {} {}".format(role, self.command, self.path), flush=True)

        def _json(self, payload, status=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                return self._json({"status": "ok"})
            if self.path == "/props":
                return self._json({"modalities": {}})
            return self._json({"error": "not found"}, status=404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")

            if self.path == "/v1/embeddings":
                texts = payload.get("input")
                if isinstance(texts, str):
                    texts = [texts]
                data = [{"index": index, "embedding": embed_vector(text)}
                        for index, text in enumerate(texts or [])]
                return self._json({"data": data})

            if self.path == "/v1/chat/completions":
                if payload.get("grammar"):
                    content = "A"
                else:
                    content = FAKE_HINT
                return self._json({"choices": [{"message": {"role": "assistant",
                                                            "content": content}}],
                                   "timings": {"prompt_n": 1}})

            return self._json({"error": "not found"}, status=404)

    return Handler


def serve(port, role):
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(role))
    print("  {} escuchando en http://127.0.0.1:{}".format(role, port), flush=True)
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--llm-port", type=int, default=8081)
    parser.add_argument("--embed-port", type=int, default=8082)
    args = parser.parse_args()

    threading.Thread(target=serve, args=(args.llm_port, "LLM"), daemon=True).start()
    print("Placa de mentira en marcha (Ctrl+C para parar):")
    serve(args.embed_port, "EMBED")


if __name__ == "__main__":
    main()
