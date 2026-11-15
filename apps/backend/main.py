"""Servidor local del juego. Sirve frontend, imágenes y API de niveles."""
import json
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from logic import GameEngine

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
engine = GameEngine()


class MathKangarooHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def do_GET(self):
        if urlparse(self.path).path == "/api/health":
            return self._send_json({"status": "ok", "problems_by_level": {str(k): len(v) for k, v in engine.problems_by_level.items()}})
        return super().do_GET()

    def do_POST(self):
        try:
            data = self._read_json()
            path = urlparse(self.path).path
            if path == "/api/level/start":
                result = engine.start_level(str(data.get("island_id", "")), int(data.get("level_number", 1)))
                return self._send_json(result, 200 if result.get("status") != "error" else 400)
            if path == "/api/level/answer":
                return self._send_json(engine.submit_level_answer(data.get("answer", "")))
            if path == "/api/level/cancel":
                return self._send_json(engine.cancel_level())
            return self._send_json({"status": "error", "message": "Endpoint no encontrado."}, 404)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            return self._send_json({"status": "error", "message": str(exc)}, 400)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), MathKangarooHandler)
    print("Juego disponible en http://127.0.0.1:8000")
    print("Comprobación de datos: http://127.0.0.1:8000/api/health")
    server.serve_forever()
