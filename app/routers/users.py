from fastapi import APIRouter, Depends

from app.core.database import Database, get_db
from app.core.security import get_current_user
from app.models.schemas import UserProfile, UserProfileUpdate

router = APIRouter(prefix="/users", tags=["Profil"])


def _to_profile(user: dict) -> UserProfile:
    return UserProfile(
        userId=user["id"],
        email=user.get("email"),
        displayName=user.get("displayName"),
        role=user.get("role", "standard"),
        verifierStatus=user.get("verifierStatus", "none"),
        reputationScore=user.get("reputationScore", 0),
        declaredCity=user.get("declaredCity"),
        preferredLanguage=user.get("preferredLanguage", "fr"),
    )


@router.get("/me", response_model=UserProfile)
def get_my_profile(user: dict = Depends(get_current_user)):
    return _to_profile(user)


@router.patch("/me", response_model=UserProfile)
def update_my_profile(
    payload: UserProfileUpdate,
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    updated = db.update("users", user["id"], updates) if updates else user
    return _to_profile(updated)
