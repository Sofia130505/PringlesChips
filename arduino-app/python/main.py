import os
import sys
import threading
import numpy as np

from arduino.app_utils import App, Bridge, Frame
from arduino.app_bricks.web_ui import WebUI

HERE = os.path.dirname(os.path.abspath(__file__))
# Buscamos la carpeta apps/backend tanto en el repo local como desplegado en la placa
for candidate in [
    os.path.abspath(os.path.join(HERE, "..", "..", "apps", "backend")),
    "/home/arduino/PringlesChips/apps/backend",
    "/home/arduino/datathon-UPC-maths-qualcomm-arduino-unoq/apps/backend",
    HERE,
]:
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)

from figuras import FIGURAS, figura  # noqa: E402
from brain import build_brain, services  # noqa: E402

ASSETS = os.path.join(os.path.dirname(HERE), "assets")

print("Estado servicios IA:", services.status(), flush=True)
tutor = build_brain()
hint_jobs = {}


def _generate_hint_worker(problem_id, prob_obj):
    try:
        res = tutor.model_hint(prob_obj)
        hint_text = res.get("hint", res) if isinstance(res, dict) else str(res)
        hint_jobs[problem_id] = {"status": "done", "hint": hint_text}
    except Exception as e:
        hint_jobs[problem_id] = {"status": "error", "hint": str(e)}


def dibujar(nombre):
    try:
        frame = Frame(np.array(figura(nombre), dtype=np.uint8))
        Bridge.call("draw", frame.to_board_bytes())
        return {"ok": True, "figura": nombre}
    except Exception as error:
        print("No se pudo dibujar {!r}: {}".format(nombre, error), flush=True)
        return {"ok": False, "figura": nombre, "error": str(error)}


ui = WebUI()

# 1. LEDs (estrella, corazon, apagar)
for _nombre in FIGURAS:
    ui.expose_api("GET", "/api/led/" + _nombre,
                  lambda nombre=_nombre: dibujar(nombre))

# 2. Juego completo (tu backend)
ui.expose_api("GET", "/api/state", lambda: tutor.state())
ui.expose_api("GET", "/api/stats", lambda: tutor.analytics())
ui.expose_api("POST", "/api/placement/start", lambda: tutor.start_placement())
ui.expose_api("POST", "/api/placement/answer", lambda body: tutor.submit_placement_answer((body or {}).get("answer", "")))
ui.expose_api("POST", "/api/level/start", lambda body: tutor.start_level(int(body["island"]), int(body["level_idx"])))
ui.expose_api("POST", "/api/level/answer", lambda body: tutor.submit_level_answer((body or {}).get("answer", "")))
ui.expose_api("POST", "/api/reset", lambda: tutor.reset())


def api_model_hint(problem_id=""):
    if not problem_id:
        return {"error": "Falta problem_id"}
    if problem_id not in hint_jobs:
        prob_obj = next((p for p in getattr(tutor, "problems", []) if p.get("id") == problem_id), {"id": problem_id})
        hint_jobs[problem_id] = {"status": "pending"}
        threading.Thread(target=_generate_hint_worker, args=(problem_id, prob_obj), daemon=True).start()
        return {"ok": True, "status": "pending"}
    return {"ok": True, **hint_jobs[problem_id]}


ui.expose_api("GET", "/api/hint/model", api_model_hint)

App.run()