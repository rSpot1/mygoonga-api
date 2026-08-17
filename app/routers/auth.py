from fastapi import APIRouter, Depends

from app.config import get_settings
from app.core.database import Database, get_db, now_iso
from app.core.security import get_current_identity
from app.models.schemas import SyncResponse

router = APIRouter(prefix="/auth", tags=["Authentification"])
settings = get_settings()
VALID_ROLES = {"standard", "verifier", "moderator", "admin"}


@router.post("/sync", response_model=SyncResponse, status_code=200)
def sync_account(identity: dict = Depends(get_current_identity), db: Database = Depends(get_db)):
    """Synchronise le compte Firebase Auth avec le profil applicatif après une première
    connexion. Crée le profil s'il n'existe pas encore, avec le rôle "standard" par défaut."""
    uid = identity["uid"]
    existing = db.get("users", uid)
    if existing:
        return SyncResponse(userId=uid, role=existing.get("role", "standard"), createdAt=existing.get("createdAt", now_iso()))

    # En mode debug local (X-Debug-Role), on permet de créer directement un compte avec
    # le rôle indiqué, pour pouvoir tester les routes réservées aux modérateurs/admins
    # sans devoir passer par le flux complet de promotion. Ignoré en production.
    debug_role = identity.get("_debugRole")
    initial_role = debug_role if (settings.DEBUG_MODE and debug_role in VALID_ROLES) else "standard"

    user = db.create(
        "users",
        {
            "email": identity.get("email"),
            "displayName": identity.get("displayName") or identity.get("email"),
            "role": initial_role,
            "verifierStatus": "none",
            "reputationScore": 0,
            "declaredCity": None,
            "preferredLanguage": "fr",
        },
        doc_id=uid,
    )
    return SyncResponse(userId=uid, role=user["role"], createdAt=user["createdAt"])
