#!/usr/bin/env python3
"""Copia el frontend a la app de App Lab y le engancha el LED.

    python3 scripts/sync_assets.py

Hace tres cosas:

1. Copia ``apps/frontend/`` -> ``arduino-app/assets/`` (borrando la copia anterior).
2. Copia ``arduino-app/web/led.js`` -> ``arduino-app/assets/led.js``.
3. Añade ``<script src="led.js"></script>`` detrás de ``<script src="app.js"></script>``
   en la copia de ``index.html``.

Así ``apps/frontend/`` **nunca** se toca: la copia es la que corre en la placa.
Vuelve a lanzarlo cada vez que cambie el frontend.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOURCE = os.path.join(ROOT, "apps", "frontend")
APP = os.path.join(ROOT, "arduino-app")
ASSETS = os.path.join(APP, "assets")
HOOK = os.path.join(APP, "web", "led.js")

TAG = '<script src="app.js"></script>'
HOOK_TAG = TAG + '\n  <script src="led.js"></script>'


def main():
    for path in (SOURCE, HOOK):
        if not os.path.exists(path):
            print("No encuentro {}".format(path), file=sys.stderr)
            return 1

    if os.path.isdir(ASSETS):
        shutil.rmtree(ASSETS)
    shutil.copytree(SOURCE, ASSETS)
    shutil.copy2(HOOK, os.path.join(ASSETS, "led.js"))

    index = os.path.join(ASSETS, "index.html")
    with open(index, "r", encoding="utf-8") as handle:
        html = handle.read()

    if HOOK_TAG in html:
        print("index.html ya tenía led.js")
    elif TAG in html:
        html = html.replace(TAG, HOOK_TAG, 1)
        with open(index, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(html)
        print("led.js enganchado en index.html")
    else:
        print("AVISO: no encuentro {} en index.html: añade la etiqueta a mano".format(TAG),
              file=sys.stderr)

    total = sum(len(files) for _, _, files in os.walk(ASSETS))
    print("assets listo: {} ficheros en {}".format(total, ASSETS))
    print()
    print("Para llevarlo a la placa (ajusta la IP y el nombre de la app):")
    print("  scp -r arduino-app arduino@<ip>:/home/arduino/ArduinoApps/aventura-mates")
    print("  ssh arduino@<ip> 'arduino-app-cli app start user:aventura-mates'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
