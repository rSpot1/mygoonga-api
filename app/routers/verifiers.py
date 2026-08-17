from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from app.core.database import Database, get_db, now_iso
from app.core.security import get_current_user, require_roles
from app.models.schemas import (
    VerifierApplicationCreated,
    VerifierApplicationDetail,
    VerifierApplicationSummary,
    VerifierReviewRequest,
    VerifierReviewResponse,
)
from app.services import exif_utils, storage

router = APIRouter(prefix="/verifiers", tags=["Vérificateurs"])


@router.post("/apply", response_model=VerifierApplicationCreated, status_code=status.HTTP_201_CREATED)
def apply_for_verifier(
    phoneNumber: str = Form(...),
    cniFront: UploadFile = File(...),
    cniBack: UploadFile = File(...),
    verificationPhoto: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Soumet une demande de statut vérificateur. Les pièces (CNI, photo) sont stockées
    dans un espace restreint : jamais exposées à d'autres utilisateurs ni aux vérificateurs,
    uniquement accessibles aux modérateurs via des URLs signées et journalisées."""

    front_bytes = cniFront.file.read()
    cniFront.file.seek(0)
    back_bytes = cniBack.file.read()
    cniBack.file.seek(0)
    verif_bytes = verificationPhoto.file.read()
    verificationPhoto.file.seek(0)

    declared_city_coords = None  # pas de géocodage de ville dans le MVP ; laissé à None
    metadata_flags: list[str] = []
    for label, raw in (("front", front_bytes), ("back", back_bytes), ("verification", verif_bytes)):
        exif = exif_utils.extract_exif(raw)
        flags = exif_utils.moderation_metadata_flags(exif, declared_city_coords)
        metadata_flags.extend(f"{label}:{flag}" for flag in flags)

    stored_front = storage.save_upload(cniFront, folder=f"cni/{user['id']}", restricted=True)
    stored_back = storage.save_upload(cniBack, folder=f"cni/{user['id']}", restricted=True)
    stored_verif = storage.save_upload(verificationPhoto, folder=f"cni/{user['id']}", restricted=True)

    application = db.create(
        "verifier_applications",
        {
            "userId": user["id"],
            "phoneNumber": phoneNumber,
            "cniFrontPath": stored_front.path,
            "cniBackPath": stored_back.path,
            "verificationPhotoPath": stored_verif.path,
            "metadataFlags": metadata_flags,
            "status": "pending",
            "submittedAt": now_iso(),
        },
    )
    db.update("users", user["id"], {"verifierStatus": "pending"})

    return VerifierApplicationCreated(applicationId=application["id"], status="pending")


@router.get("/applications", response_model=list[VerifierApplicationSummary])
def list_applications(
    _: dict = Depends(require_roles("moderator", "admin")),
    db: Database = Depends(get_db),
):
    """Liste les demandes en attente. Ne renvoie jamais les documents bruts, uniquement
    les métadonnées extraites, conformément au principe de confidentialité (§6)."""
    apps = db.list("verifier_applications", filters=[("status", "==", "pending")])
    return [
        VerifierApplicationSummary(
            applicationId=a["id"],
            userId=a["userId"],
            submittedAt=a.get("submittedAt", a.get("createdAt")),
            metadataFlags=a.get("metadataFlags", []),
        )
        for a in apps
    ]


@router.get("/applications/{application_id}", response_model=VerifierApplicationDetail)
def get_application_detail(
    application_id: str,
    request: Request,
    moderator: dict = Depends(require_roles("moderator", "admin")),
    db: Database = Depends(get_db),
):
    """Détail d'une demande, avec accès temporaire et journalisé aux documents (§6, §11)."""
    app_doc = db.get("verifier_applications", application_id)
    if not app_doc:
        raise HTTPException(status_code=404, detail="Demande introuvable.")

    base_url = str(request.base_url)
    front_url = storage.sign_path(app_doc["cniFrontPath"], base_url)
    back_url = storage.sign_path(app_doc["cniBackPath"], base_url)
    verif_url = storage.sign_path(app_doc["verificationPhotoPath"], base_url)

    # Journalisation systématique de l'accès aux données sensibles (§11).
    db.create(
        "audit_log",
        {
            "accessedBy": moderator["id"],
            "accessedAt": now_iso(),
            "action": "view_verifier_application",
            "targetCollection": "verifier_applications",
            "targetId": application_id,
        },
    )

    return VerifierApplicationDetail(
        applicationId=app_doc["id"],
        cniFrontUrl=front_url,
        cniBackUrl=back_url,
        verificationPhotoUrl=verif_url,
        metadataFlags=app_doc.get("metadataFlags", []),
        phoneNumber=app_doc.get("phoneNumber", ""),
    )


@router.post("/applications/{application_id}/review", response_model=VerifierReviewResponse)
def review_application(
    application_id: str,
    payload: VerifierReviewRequest,
    moderator: dict = Depends(require_roles("moderator", "admin")),
    db: Database = Depends(get_db),
):
    """Valide ou rejette une demande. Le modérateur reste seul décisionnaire (§7.2) :
    l'API n'automatise jamais cette décision."""
    if payload.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=422, detail="decision doit être 'approved' ou 'rejected'.")

    app_doc = db.get("verifier_applications", application_id)
    if not app_doc:
        raise HTTPException(status_code=404, detail="Demande introuvable.")

    db.update(
        "verifier_applications",
        application_id,
        {"status": payload.decision, "reason": payload.reason, "reviewedBy": moderator["id"]},
    )

    if payload.decision == "approved":
        db.update("users", app_doc["userId"], {"role": "verifier", "verifierStatus": "approved"})
    else:
        db.update("users", app_doc["userId"], {"verifierStatus": "rejected"})

    # Notification à l'utilisateur : stockée comme document ; à relier à un vrai canal
    # (push notification / email) côté intégration finale.
    db.create(
        "notifications",
        {
            "userId": app_doc["userId"],
            "type": "verifier_application_reviewed",
            "status": payload.decision,
            "reason": payload.reason,
        },
    )

    return VerifierReviewResponse(applicationId=application_id, status=payload.decision)
