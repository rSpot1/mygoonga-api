"""
Service de stockage des fichiers (médias soumis à analyse, pièces CNI, photos de vérification).

Deux modes :
- local  : écrit sur disque dans LOCAL_STORAGE_DIR (par défaut ./storage). Pratique en
           développement. Les fichiers "restreints" (CNI) sont accessibles uniquement via
           une URL signée maison (voir sign_path / verify_signed_path).
- firebase : envoie vers Firebase Storage. Les fichiers restreints sont placés dans un
             dossier réservé (cni/) dont les règles de sécurité Storage interdisent la
             lecture publique (voir README, section Firebase Storage Rules). Les URLs
             signées sont générées par le SDK Admin (expirantes).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import UploadFile

from app.config import get_settings

settings = get_settings()


@dataclass
class StoredFile:
    path: str  # chemin/clé interne (utilisé pour retrouver le fichier)
    content_type: Optional[str]
    size: int
    restricted: bool


def _local_root() -> Path:
    root = Path(settings.LOCAL_STORAGE_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_upload(file: UploadFile, folder: str, restricted: bool = False) -> StoredFile:
    """Enregistre un fichier envoyé par le client. Renvoie un descripteur interne
    (jamais une URL publique directe pour un fichier restreint)."""
    content = file.file.read()
    ext = Path(file.filename or "").suffix
    key = f"{folder}/{uuid.uuid4().hex}{ext}"

    if settings.STORAGE_MODE == "firebase":
        from app.core.firebase_admin_client import get_storage_bucket

        bucket = get_storage_bucket()
        blob = bucket.blob(key)
        blob.upload_from_string(content, content_type=file.content_type)
        if not restricted:
            blob.make_public()
    else:
        dest = _local_root() / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    return StoredFile(path=key, content_type=file.content_type, size=len(content), restricted=restricted)


def local_file_bytes(key: str) -> bytes:
    return (_local_root() / key).read_bytes()


def _signature(key: str, expires_at: int) -> str:
    msg = f"{key}:{expires_at}".encode()
    return hmac.new(settings.SIGNED_URL_SECRET.encode(), msg, hashlib.sha256).hexdigest()


def sign_path(key: str, base_url: str) -> str:
    """Génère une URL signée et expirante pour un fichier restreint (ex : CNI).
    En mode firebase, délègue au SDK Admin (signed URL réelle du bucket)."""
    if settings.STORAGE_MODE == "firebase":
        from app.core.firebase_admin_client import get_storage_bucket
        import datetime

        bucket = get_storage_bucket()
        blob = bucket.blob(key)
        expiration = datetime.timedelta(seconds=settings.SIGNED_URL_EXPIRY_SECONDS)
        return blob.generate_signed_url(expiration=expiration, method="GET")

    expires_at = int(time.time()) + settings.SIGNED_URL_EXPIRY_SECONDS
    sig = _signature(key, expires_at)
    return f"{base_url.rstrip('/')}/files/signed/{key}?expires={expires_at}&sig={sig}"


def verify_signed_path(key: str, expires: int, sig: str) -> bool:
    if int(time.time()) > expires:
        return False
    expected = _signature(key, expires)
    return hmac.compare_digest(expected, sig)


def public_url(key: str, base_url: str) -> str:
    if settings.STORAGE_MODE == "firebase":
        from app.core.firebase_admin_client import get_storage_bucket

        bucket = get_storage_bucket()
        blob = bucket.blob(key)
        return blob.public_url
    return f"{base_url.rstrip('/')}/files/public/{key}"
