"""
Authentification et autorisation.

Flux normal (production) :
  - Le client Flutter envoie `Authorization: Bearer <token Firebase>`
  - `verify_token` vérifie le token via firebase_admin.auth.verify_id_token
  - `get_current_user` charge (ou crée) le profil applicatif correspondant dans la base

Flux de test local (DEBUG_MODE=true et Firebase non configuré) :
  - Le client peut envoyer les en-têtes `X-Debug-Uid` et `X-Debug-Role` pour simuler
    un utilisateur authentifié, sans avoir à configurer Firebase. Ce mode ne doit
    JAMAIS être activé en production (DEBUG_MODE=false désactive complètement ce chemin).
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from app.config import get_settings
from app.core.database import Database, get_db, now_iso

settings = get_settings()


class AuthError(HTTPException):
    def __init__(self, detail: str = "Authentification invalide ou absente."):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _verify_firebase_token(token: str) -> dict:
    from firebase_admin import auth as firebase_auth

    from app.core.firebase_admin_client import get_firebase_app

    try:
        # Le SDK Admin doit etre initialise avant toute verification de token,
        # independamment de USE_MOCK_DB / STORAGE_MODE : la verification d'un
        # vrai token Firebase (envoye par l'app Flutter) exige toujours de vraies
        # informations d'identification Firebase, meme si la base de donnees et
        # le stockage de fichiers restent en mode local pour le developpement.
        get_firebase_app()
    except Exception as exc:
        raise AuthError(
            "L'API a reçu un token Firebase à vérifier, mais les identifiants "
            "Firebase Admin ne sont pas configurés côté serveur. Renseignez "
            "FIREBASE_CREDENTIALS_PATH (ou FIREBASE_CREDENTIALS_JSON) dans le "
            f".env de l'API. Erreur d'origine : {exc}"
        ) from exc

    try:
        decoded = firebase_auth.verify_id_token(token)
    except Exception as exc:
        raise AuthError(f"Token Firebase invalide : {exc}") from exc
    return {
        "uid": decoded["uid"],
        "email": decoded.get("email"),
        "displayName": decoded.get("name"),
        "emailVerified": decoded.get("email_verified", False),
    }


def _decode_identity(
    authorization: Optional[str],
    debug_uid: Optional[str],
    debug_role: Optional[str],
    debug_email: Optional[str],
) -> dict:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if settings.USE_MOCK_DB and settings.DEBUG_MODE and token.startswith("debug:"):
            # Permet aussi de passer un faux token du type "debug:<uid>" en Authorization
            uid = token.split(":", 1)[1] or "debug-user"
            return {"uid": uid, "email": f"{uid}@example.test", "displayName": uid, "emailVerified": True}
        return _verify_firebase_token(token)

    if settings.DEBUG_MODE and debug_uid:
        return {
            "uid": debug_uid,
            "email": debug_email or f"{debug_uid}@example.test",
            "displayName": debug_uid,
            "emailVerified": True,
            "_debugRole": debug_role,
        }

    raise AuthError(
        "En-tête Authorization manquant. Envoyez 'Authorization: Bearer <token Firebase>', "
        "ou, en mode debug local, les en-têtes 'X-Debug-Uid' / 'X-Debug-Role'."
    )


def get_current_identity(
    authorization: Optional[str] = Header(None),
    x_debug_uid: Optional[str] = Header(None, alias="X-Debug-Uid"),
    x_debug_role: Optional[str] = Header(None, alias="X-Debug-Role"),
    x_debug_email: Optional[str] = Header(None, alias="X-Debug-Email"),
) -> dict:
    """Décode l'identité de l'appelant sans nécessiter que son profil existe déjà en base.
    Utilisé uniquement par POST /auth/sync."""
    return _decode_identity(authorization, x_debug_uid, x_debug_role, x_debug_email)


def get_current_user(
    identity: dict = Depends(get_current_identity),
    db: Database = Depends(get_db),
) -> dict:
    """Charge le profil applicatif de l'utilisateur connecté. Le profil doit déjà exister
    (créé via POST /auth/sync lors de la première connexion)."""
    user = db.get("users", identity["uid"])
    if user is None:
        # Auto-création tolérante : en mode debug ou pour un premier appel direct,
        # on crée un profil "standard" minimal plutôt que d'échouer.
        role = identity.get("_debugRole") or "standard"
        user = db.create(
            "users",
            {
                "email": identity.get("email"),
                "displayName": identity.get("displayName") or identity.get("email"),
                "role": role,
                "verifierStatus": "none",
                "reputationScore": 0,
                "declaredCity": None,
                "preferredLanguage": "fr",
            },
            doc_id=identity["uid"],
        )
    return user


def require_roles(*allowed_roles: str):
    """Dépendance FastAPI : n'autorise l'accès qu'aux rôles listés.
    Le contrôle est fait côté serveur, jamais uniquement côté client Flutter."""

    def dependency(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Accès réservé aux rôles : {', '.join(allowed_roles)}.",
            )
        return user

    return dependency