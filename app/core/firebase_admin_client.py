"""
Initialisation paresseuse (lazy) du SDK Firebase Admin.
N'est appelé que lorsque USE_MOCK_DB=false et/ou STORAGE_MODE=firebase, donc jamais
en mode "test rapide sans configuration".
"""
from __future__ import annotations

import json
import threading
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore, storage

from app.config import get_settings

settings = get_settings()

_app_lock = threading.Lock()
_app: Optional[firebase_admin.App] = None


def _build_credentials() -> credentials.Base:
    if settings.FIREBASE_CREDENTIALS_JSON:
        info = json.loads(settings.FIREBASE_CREDENTIALS_JSON)
        return credentials.Certificate(info)
    if settings.FIREBASE_CREDENTIALS_PATH:
        return credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
    raise RuntimeError(
        "Aucun identifiant Firebase trouvé. Définissez FIREBASE_CREDENTIALS_JSON "
        "(contenu du fichier service-account.json) ou FIREBASE_CREDENTIALS_PATH "
        "(chemin vers ce fichier)."
    )


def get_firebase_app() -> firebase_admin.App:
    global _app
    if _app is None:
        with _app_lock:
            if _app is None:
                cred = _build_credentials()
                options = {}
                if settings.FIREBASE_STORAGE_BUCKET:
                    options["storageBucket"] = settings.FIREBASE_STORAGE_BUCKET
                if settings.FIREBASE_PROJECT_ID:
                    options["projectId"] = settings.FIREBASE_PROJECT_ID
                _app = firebase_admin.initialize_app(cred, options)
    return _app


def get_firestore_client():
    get_firebase_app()
    return firestore.client()


def get_storage_bucket():
    get_firebase_app()
    return storage.bucket()
