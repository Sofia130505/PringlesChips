import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from logic import GameEngine

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))

engine = GameEngine()

DEBUG_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Backend Test</title></head>
<body style="font-family:sans-serif;max-width:700px;margin:2rem auto;">
  <h2>Backend Canguro Operativo (sin esperar al Frontend)</h2>
  <button onclick="call('/api/state','GET')">Ver Estado</button>
  <button onclick="call('/api/placement/start','POST')">Iniciar Test Nivel</button>
  <button onclick="call('/api/level/start','POST',{island:0,level_idx:0})">Jugar Isla 0 - Nivel 0</button>
  <button onclick="call('/api/reset','POST')">Resetear Perfil</button>
  <div style="margin-top:1rem;">
    Responder:
    <button onclick="ans('A')">A</button>
    <button onclick="ans('B')">B</button>
    <button onclick="ans('C')">C</button>
    <button onclick="ans('D')">D</button>
    <button onclick="ans('E')">E</button>
    <button onclick="ans('DONT_KNOW')">No lo sé</button>
  </div>
  <pre id="out" style="background:#f4f4f4;padding:1rem;white-space:pre-wrap;margin-top:1rem;"></pre>
  <script>
    let mode = 'placement';
    async function call(url, method, body) {
      if (url.includes('placement')) mode = 'placement';
      if (url.includes('level')) mode = 'level';
      const r = await fetch(url, {method, headers:{'Content-Type':'application/json'}, body: body ? JSON.stringify(body) : null});
      document.getElementById('out').textContent = JSON.stringify(await r.json(), null, 2);
    }
    function ans(letter) {
      call(mode === 'placement' ? '/api/placement/answer' : '/api/level/answer', 'POST', {answer: letter});
    }
  </script>
</body></html>"""

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
        if self.path == "/api/state":
            return self._send_json(engine.get_full_state())

        if self.path.startswith("/data/"):
            full_path = os.path.abspath(os.path.join(DATA_DIR, "..", self.path.lstrip("/")))
            if full_path.startswith(DATA_DIR) and os.path.isfile(full_path):
                with open(full_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        # Si index.html aún está vacío, sirve la página de pruebas integrada
        index_file = os.path.join(FRONTEND_DIR, "index.html")
        if self.path in ("/", "/index.html") and (not os.path.exists(index_file) or os.path.getsize(index_file) == 0):
            body = DEBUG_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        super().do_GET()

    def do_POST(self):
        data = self._read_json()
        if self.path == "/api/placement/start":
            self._send_json(engine.start_placement())
        elif self.path == "/api/placement/answer":
            self._send_json(engine.submit_placement_answer(data.get("answer", "")))
        elif self.path == "/api/level/start":
            self._send_json(engine.start_level(int(data["island"]), int(data["level_idx"])))
        elif self.path == "/api/level/answer":
            self._send_json(engine.submit_level_answer(data.get("answer", "")))
        elif self.path == "/api/reset":
            self._send_json(engine.reset_profile())
        else:
            self._send_json({"error": "Endpoint no encontrado"}, status=404)

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8000), MathKangarooHandler)
    print("Servidor listo en http://127.0.0.1:8000")
    server.serve_forever()