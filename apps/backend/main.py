import json
import os
import sys
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

BACKEND_DIR = os.path.abspath(os.path.dirname(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from brain import build_brain, services

FRONTEND_DIR = os.path.abspath(os.path.join(BACKEND_DIR, "..", "frontend"))
DATA_DIR = os.path.abspath(os.path.join(BACKEND_DIR, "..", "..", "data"))

# 1. Comprobar servicios del Arduino (8081 LLM y 8082 Embeddings) al arrancar
print("Estado de servicios IA:", services.status())

# 2. Inicializar el cerebro (carga data/*.jsonl, game_state.db e index.db)
tutor = build_brain()
print("Ficheros cargados por brain:", getattr(tutor, "loaded", "OK"))

# Estado en memoria para pistas asíncronas generadas por el modelo (hilo en segundo plano)
hint_jobs = {}  # {problem_id: {"status": "pending"|"done", "hint": "..."}}


def _generate_hint_worker(problem_id, prob_obj):
    try:
        res = tutor.model_hint(prob_obj)
        hint_text = res.get("hint", res) if isinstance(res, dict) else str(res)
        hint_jobs[problem_id] = {"status": "done", "hint": hint_text}
    except Exception as e:
        hint_jobs[problem_id] = {"status": "error", "hint": str(e)}


class MathKangarooHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FRONTEND_DIR, **kwargs)

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/state":
            return self._send_json(tutor.state())

        if path == "/api/stats":
            return self._send_json(tutor.analytics())

        # Endpoint asíncrono para pistas del LLM (regla 1 de API.md: sin bloquear)
        if path == "/api/hint/model":
            qs = parse_qs(parsed.query)
            prob_id = qs.get("problem_id", [""])[0]
            if not prob_id:
                return self._send_json({"error": "Falta problem_id"}, status=400)

            if prob_id not in hint_jobs:
                # Buscamos el problema en el banco cargado del cerebro
                prob_obj = next((p for p in getattr(tutor, "problems", []) if p.get("id") == prob_id), {"id": prob_id})
                hint_jobs[prob_id] = {"status": "pending"}
                t = threading.Thread(target=_generate_hint_worker, args=(prob_id, prob_obj), daemon=True)
                t.start()
                return self._send_json({"ok": True, "status": "pending"})

            return self._send_json({"ok": True, **hint_jobs[prob_id]})

        # Servir imágenes PNG de los problemas desde data/images/
        if path.startswith("/data/images/"):
            full_path = os.path.abspath(os.path.join(DATA_DIR, "..", path.lstrip("/")))
            images_dir = os.path.join(DATA_DIR, "images")
            if full_path.startswith(images_dir) and os.path.isfile(full_path):
                with open(full_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        super().do_GET()

    def do_POST(self):
        data = self._read_json()

        if self.path == "/api/placement/start":
            res = tutor.start_placement()
            return self._send_json(res, status=409 if "error" in res else 200)

        if self.path == "/api/placement/answer":
            res = tutor.submit_placement_answer(data.get("answer", ""))
            return self._send_json(res, status=409 if "error" in res else 200)

        if self.path == "/api/level/start":
            res = tutor.start_level(int(data["island"]), int(data["level_idx"]))
            return self._send_json(res, status=409 if "error" in res else 200)

        if self.path == "/api/level/answer":
            res = tutor.submit_level_answer(data.get("answer", ""))
            return self._send_json(res, status=409 if "error" in res else 200)

        if self.path == "/api/reset":
            return self._send_json(tutor.reset())

        return self._send_json({"error": "Endpoint no encontrado"}, status=404)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8000), MathKangarooHandler)
    print("Servidor web activo en http://127.0.0.1:8000")
    server.serve_forever()