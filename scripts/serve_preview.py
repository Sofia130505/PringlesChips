#!/usr/bin/env python3
"""Prueba la web de la app y la matriz LED **sin la placa**.

    python scripts/serve_preview.py          -> abre http://127.0.0.1:7100

Sirve `arduino-app/assets/` (lo genera `scripts/sync_assets.py`) y contesta a los
endpoints `/api/led/...` como lo haría la placa, pero dibujando la figura en la
terminal:

    [LED] estrella
    ......#......
    .....###.....
    ...

Así compruebas el enganche de la página (isla -> estrella, nivel -> corazón) sin
hardware. Lo que NO prueba: el Bridge ni el sketch, eso solo en la placa.
"""
import argparse
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "arduino-app", "assets")
FIGURAS_DIR = os.path.join(ROOT, "arduino-app", "python")

if FIGURAS_DIR not in sys.path:
    sys.path.insert(0, FIGURAS_DIR)

try:
    from figuras import FIGURAS, preview
except ImportError:                                    # pragma: no cover
    FIGURAS, preview = (), None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ASSETS, **kwargs)

    def log_message(self, fmt, *args):
        """Silencio: en la terminal solo queremos ver lo de la matriz."""

    def _send(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/led/"):
            nombre = self.path.rsplit("/", 1)[-1].split("?")[0]
            print("\n[LED] {}".format(nombre), flush=True)
            if preview is not None and nombre in FIGURAS:
                print(preview(nombre), flush=True)
            return self._send({"ok": True, "figura": nombre})
        return super().do_GET()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=7100)
    args = parser.parse_args()

    if not os.path.exists(os.path.join(ASSETS, "index.html")):
        print("No hay {}\\index.html".format(ASSETS), file=sys.stderr)
        print("Ejecuta antes:  python scripts/sync_assets.py", file=sys.stderr)
        return 1

    print("Sirviendo {} en http://127.0.0.1:{}".format(ASSETS, args.port))
    print("Abre esa dirección, pulsa una isla y mira aquí (Ctrl+C para parar).", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
