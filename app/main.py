from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import admin, auth, events, files, media, users, verifiers
from app.services import huggingface

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "API de MyGoonga — vérification collaborative de médias et d'événements locaux. "
        "Pilier 1 : indices de cohérence technique d'un média. "
        "Pilier 2 : confirmation par des témoins de proximité réelle."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(verifiers.router)
app.include_router(media.router)
app.include_router(events.router)
app.include_router(admin.router)
app.include_router(files.router)


@app.get("/", tags=["Statut"])
def root():
    return {
        "service": settings.APP_NAME,
        "status": "en ligne",
        "mode": "base en mémoire (test)" if settings.USE_MOCK_DB else "Firestore (production)",
        "huggingFaceConfigured": huggingface.is_configured(),
        "docs": "/docs",
    }


@app.get("/health", tags=["Statut"])
def health():
    return JSONResponse({"status": "ok"})
