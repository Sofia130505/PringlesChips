# Contrato del backend (para quien monte el servidor web)

`apps/backend/brain/` es **el cerebro**: no abre ningún puerto, no sirve ficheros
y no sabe nada de HTTP. El servidor web lo monta otra persona encima de estas
funciones. Este documento es el contrato entre las dos partes.

## Cómo se usa desde Python

```python
import sys
sys.path.insert(0, "apps/backend")

from brain import build_brain, services

estado_servicios = services.status()        # {"ok": bool, "LLM": {...}, "EMBED": {...}}
tutor = build_brain()                       # problemas + SQLite + índice (si existe)
```

`build_brain()` hace tres cosas: carga `data/*.jsonl`, abre `data/game_state.db`
y, si existe `data/index.db`, carga el índice RAG. `tutor.loaded` dice qué
ficheros se han leído.

## Función ↔ endpoint

| Método y ruta propuestos | Función del cerebro | Devuelve |
|---|---|---|
| `GET /api/state` | `tutor.state()` | `placement_done`, `assigned_island`, `unlocked_accessories`, `islands[]` |
| `POST /api/placement/start` | `tutor.start_placement()` | `in_progress` + pregunta 1 |
| `POST /api/placement/answer` `{answer}` | `tutor.submit_placement_answer(answer)` | `in_progress` o `finished` |
| `POST /api/level/start` `{island, level_idx}` | `tutor.start_level(island, level_idx)` | `next_problem` / `level_failed` / `level_completed` |
| `POST /api/level/answer` `{answer}` | `tutor.submit_level_answer(answer)` | ver estados abajo |
| `GET /api/stats` | `tutor.analytics()` | `{"analytics_by_island": [...]}` |
| `POST /api/reset` | `tutor.reset()` | el mismo JSON que `/api/state` |
| `GET /api/hint/model?problem_id=…` | `tutor.model_hint(problema)` | pista del modelo (**en un hilo**, ver abajo) |

`answer` es `"A"`…`"E"` o `"DONT_KNOW"`. Con un valor raro, la respuesta cuenta
como fallo (no lanza excepción).

## Estados que devuelve `submit_level_answer`

| `status` | Cuándo | Qué enseñar |
|---|---|---|
| `next_problem` | acierto | `feedback: "correct"`, siguiente `problem` y `remaining` |
| `retry_with_hint` | primer fallo | `hint`, `hint_source`, `similar_problem_id` y el mismo `problem` |
| `next_problem` + `feedback: "incorrect_moved_to_review"` | segundo fallo | el problema va al repaso final |
| `level_failed` | falló el repaso | `message`; se puede reintentar el nivel |
| `level_completed` | nivel superado | `reward.unlocked`, `reward.accessory`, `reward.island` |

Si no hay sesión activa, devuelve `{"error": "..."}` → contesta `409` o `400`.

`level_failed` puede llegar dentro de `submit_level_answer` o de `start_level`:
en los dos casos la sesión ha terminado.

## Forma de un `problem`

```json
{
  "id": "lvl-0_2015_13",
  "language": "eng",
  "level": 0,
  "text": "13. For 3 days, ...",
  "options": {"A": "12", "B": "15", "C": "18", "D": "20", "E": "24"},
  "image_url": "/data/images/lvl-0_2015_13_eng.png"
}
```

Nunca incluye `label`. `image_url` viene vacío si no hay PNG del enunciado.
Si sirves las imágenes, hazlo desde `data/images/` y solo para claves conocidas.

## Las tres reglas que no se pueden romper

1. **Nada de modelo dentro de un handler.** `hint()` es instantánea (índice
   local + plantilla). `model_hint()` tarda de 5 a 30 s en la placa: se lanza en
   un `threading.Thread`, se contesta `{"ok": true}` y la página pregunta por el
   resultado (`/status`), como hace el ejemplo oficial de `web_ui`.
2. **Comprobar los servicios al arrancar** (`services.status()`). Si `8081` o
   `8082` están caídos, el juego puede seguir (pistas sin modelo, sin RAG), pero
   hay que decirlo en el log.
3. **Determinismo.** `build_brain()` ya fija `random.seed(SEED)` de `config.env`.
   No uses `time`, `uuid` ni `random` sin semilla en las respuestas.

## Arranque y comprobaciones

```bash
python apps/backend/main.py               # informe de servicios + datos + índice
python apps/backend/main.py --json        # el mismo informe en JSON
python apps/backend/main.py --wait 60     # espera a que suban 8081/8082
python apps/backend/main.py --build-index # construye data/index.db (RAG)
python apps/backend/main.py --demo        # partida de prueba por consola
```

El servidor antiguo, que sirve `apps/frontend` en el puerto 8000, sigue vivo en
`apps/backend/web_demo.py` para no romper la demo durante la transición.

## Sobre el banco de problemas

Ahora mismo `data/` solo tiene `sample_problems.jsonl` (5 problemas). Cuando
estén `data/train.jsonl` y `data/val.jsonl`:

```bash
python apps/backend/main.py --build-index --languages eng
```

`data/train.jsonl`, `data/val.jsonl`, `data/images/` y `data/index.db` **no se
suben al repositorio** (licencia de investigación de M3Kang).
