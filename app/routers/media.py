from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status

from app.core.database import Database, get_db, now_iso
from app.core.security import get_current_user
from app.config import get_settings
from app.models.schemas import HumanReviewResponse, MediaAnalysisResult, MediaAnalyzeAccepted
from app.services import ela, exif_utils, gemini_vision, huggingface, quota, storage

settings = get_settings()
GEMINI_QUOTA_COUNTER = "gemini_vision_analysis"

router = APIRouter(prefix="/media", tags=["Analyse de média"])

IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _run_analysis(db: Database, analysis_id: str, file_bytes: bytes, content_type: Optional[str]) -> None:
    """Exécute l'analyse de cohérence (traitement "asynchrone" simulé via BackgroundTasks).
    En production sur Render, ceci peut être déporté vers une file de tâches (ex: Celery/RQ)
    si les volumes le justifient ; pour le MVP, un traitement en tâche de fond FastAPI suffit."""
    coherence_flags: list[str] = []
    reverse_matches: list[dict] = []
    explanations: list[str] = []
    ai_description: Optional[str] = None

    is_image = content_type in IMAGE_CONTENT_TYPES

    if is_image:
        exif = exif_utils.extract_exif(file_bytes)
        if not exif.get("hasExif"):
            coherence_flags.append("noMetadata")
        if exif.get("looksLikeScreenshot"):
            coherence_flags.append("possibleScreenshot")

        ela_result = ela.compute_ela(file_bytes)
        if ela_result.get("applicable") and ela_result.get("anomalyDetected"):
            coherence_flags.append("elaAnomaly")
        if ela_result.get("applicable"):
            explanations.append(ela_result["explanation"])

        # Recherche d'image inversée sur les analyses déjà en base (approximation MVP,
        # voir README pour les limites de cette approche).
        known = db.list("media_embeddings", limit=500)
        reverse = huggingface.reverse_image_search(file_bytes, known)
        if reverse.get("available"):
            reverse_matches = reverse.get("matches", [])
            if reverse_matches:
                coherence_flags.append("reverseMatchFound")
            if reverse.get("vector"):
                db.create(
                    "media_embeddings",
                    {"analysisId": analysis_id, "vector": reverse["vector"], "submittedAt": now_iso()},
                )
        else:
            explanations.append(
                "Recherche d'image inversée non disponible : " + reverse.get("reason", "")
            )

        # Analyse visuelle IA (Gemini), plafonnée à un quota journalier de sécurité
        # indépendant du quota réel du compte Google (voir app/services/quota.py).
        if gemini_vision.is_configured():
            allowed, _count = quota.check_and_increment(
                db, GEMINI_QUOTA_COUNTER, settings.GEMINI_DAILY_IMAGE_LIMIT
            )
            if allowed:
                ai_result = gemini_vision.analyze_image(file_bytes, content_type)
                if ai_result.get("available"):
                    ai_description = ai_result["description"]
                    if ai_result.get("flagged"):
                        coherence_flags.append("aiVisualConcern")
                else:
                    explanations.append(
                        "Analyse IA non disponible : " + ai_result.get("reason", "")
                    )
            else:
                explanations.append(
                    "Analyse IA non effectuée : quota journalier de test atteint."
                )
    else:
        explanations.append(
            "Ce type de média ne bénéficie pour l'instant que de l'extraction de métadonnées "
            "de base ; l'analyse ELA et la recherche inversée sont réservées aux images dans ce MVP."
        )

    if not coherence_flags:
        explanations.append(
            "Aucun signal d'incohérence détecté par les vérifications automatiques. "
            "Ceci ne garantit pas l'authenticité du contenu."
        )

    db.update(
        "media_analyses",
        analysis_id,
        {
            "status": "done",
            "coherenceFlags": coherence_flags,
            "reverseMatches": reverse_matches,
            "explanation": " ".join(explanations),
            "aiDescription": ai_description,
        },
    )


@router.post("/analyze", response_model=MediaAnalyzeAccepted, status_code=status.HTTP_202_ACCEPTED)
def analyze_media(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    context: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    file_bytes = file.file.read()
    file.file.seek(0)
    stored = storage.save_upload(file, folder=f"media/{user['id']}", restricted=False)

    analysis = db.create(
        "media_analyses",
        {
            "submittedBy": user["id"],
            "mediaPath": stored.path,
            "context": context,
            "status": "processing",
            "coherenceFlags": [],
            "reverseMatches": [],
            "explanation": "",
            "aiDescription": None,
            "humanReviewStatus": None,
        },
    )

    background_tasks.add_task(_run_analysis, db, analysis["id"], file_bytes, file.content_type)

    return MediaAnalyzeAccepted(analysisId=analysis["id"], status="processing")


@router.get("/analyze/{analysis_id}", response_model=MediaAnalysisResult)
def get_analysis(
    analysis_id: str,
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    analysis = db.get("media_analyses", analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analyse introuvable.")
    return MediaAnalysisResult(
        analysisId=analysis["id"],
        status=analysis.get("status", "processing"),
        coherenceFlags=analysis.get("coherenceFlags", []),
        reverseMatches=analysis.get("reverseMatches", []),
        explanation=analysis.get("explanation", ""),
        aiDescription=analysis.get("aiDescription"),
    )


@router.post("/analyze/{analysis_id}/request-human-review", response_model=HumanReviewResponse)
def request_human_review(
    analysis_id: str,
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    analysis = db.get("media_analyses", analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analyse introuvable.")
    db.update("media_analyses", analysis_id, {"humanReviewStatus": "pending"})
    return HumanReviewResponse(analysisId=analysis_id, humanReviewStatus="pending")