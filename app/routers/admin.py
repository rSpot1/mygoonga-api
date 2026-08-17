from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database import Database, get_db
from app.core.security import require_roles
from app.models.schemas import AuditLogEntry, RoleUpdateRequest, UserProfile

router = APIRouter(prefix="/admin", tags=["Administration"])

VALID_ROLES = {"standard", "verifier", "moderator", "admin"}


@router.get("/users", response_model=list[UserProfile])
def list_users(
    role: Optional[str] = Query(None),
    _: dict = Depends(require_roles("admin")),
    db: Database = Depends(get_db),
):
    filters = [("role", "==", role)] if role else None
    users = db.list("users", filters=filters)
    return [
        UserProfile(
            userId=u["id"],
            email=u.get("email"),
            displayName=u.get("displayName"),
            role=u.get("role", "standard"),
            verifierStatus=u.get("verifierStatus", "none"),
            reputationScore=u.get("reputationScore", 0),
            declaredCity=u.get("declaredCity"),
        )
        for u in users
    ]


@router.patch("/users/{user_id}/role", response_model=UserProfile)
def update_user_role(
    user_id: str,
    payload: RoleUpdateRequest,
    admin: dict = Depends(require_roles("admin")),
    db: Database = Depends(get_db),
):
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"role doit être l'un de {sorted(VALID_ROLES)}.")

    target = db.get("users", user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

    updated = db.update("users", user_id, {"role": payload.role})

    db.create(
        "audit_log",
        {
            "accessedBy": admin["id"],
            "accessedAt": updated.get("updatedAt"),
            "action": f"role_change:{payload.reason or 'no_reason'}",
            "targetCollection": "users",
            "targetId": user_id,
        },
    )

    return UserProfile(
        userId=updated["id"],
        email=updated.get("email"),
        displayName=updated.get("displayName"),
        role=updated.get("role", "standard"),
        verifierStatus=updated.get("verifierStatus", "none"),
        reputationScore=updated.get("reputationScore", 0),
        declaredCity=updated.get("declaredCity"),
    )


@router.get("/audit-log", response_model=list[AuditLogEntry])
def get_audit_log(
    _: dict = Depends(require_roles("admin")),
    db: Database = Depends(get_db),
):
    entries = db.list("audit_log", limit=200)
    return [
        AuditLogEntry(
            id=e["id"],
            accessedBy=e.get("accessedBy", ""),
            accessedAt=e.get("accessedAt", e.get("createdAt", "")),
            action=e.get("action", ""),
            targetCollection=e.get("targetCollection", ""),
            targetId=e.get("targetId", ""),
        )
        for e in entries
    ]
