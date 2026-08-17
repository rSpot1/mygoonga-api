"""
Sert les fichiers stockés en local (STORAGE_MODE=local). En production avec
STORAGE_MODE=firebase, ces routes ne sont pas utilisées : Firebase Storage sert
directement les fichiers via ses propres URLs (publiques ou signées).
"""
from fastapi import APIRouter, HTTPException, Query, Response

from app.config import get_settings
from app.services import storage

router = APIRouter(prefix="/files", tags=["Fichiers (mode local)"])
settings = get_settings()


def _guess_content_type(key: str) -> str:
    lower = key.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    return "application/octet-stream"


@router.get("/public/{key:path}")
def get_public_file(key: str):
    if settings.STORAGE_MODE != "local":
        raise HTTPException(status_code=404, detail="Mode de stockage local désactivé.")
    try:
        content = storage.local_file_bytes(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Fichier introuvable.")
    return Response(content=content, media_type=_guess_content_type(key))


@router.get("/signed/{key:path}")
def get_signed_file(key: str, expires: int = Query(...), sig: str = Query(...)):
    if settings.STORAGE_MODE != "local":
        raise HTTPException(status_code=404, detail="Mode de stockage local désactivé.")
    if not storage.verify_signed_path(key, expires, sig):
        raise HTTPException(status_code=403, detail="Lien expiré ou signature invalide.")
    try:
        content = storage.local_file_bytes(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Fichier introuvable.")
    return Response(content=content, media_type=_guess_content_type(key))
