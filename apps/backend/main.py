from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from logic import ejecutar_proceso

app = FastAPI(title="Hackathon Engine API")

# Habilitar CORS para que el frontend pueda llamar sin bloqueos
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/api/run")
def run_pipeline():
    return ejecutar_proceso()