"""
Analyse visuelle d'image via l'API Google Gemini (modèle multimodal gemini-2.5-flash
par défaut). Utilisé en complément des vérifications techniques existantes
(métadonnées EXIF, analyse ELA, recherche inversée) pour donner une lecture du
CONTENU visuel de l'image (cohérence de la scène, signes de montage grossier,
éléments contradictoires) — jamais un verdict d'authenticité tranché, conformément
à la philosophie du reste de l'analyse.

Nécessite une clé gratuite obtenue sur https://aistudio.google.com/apikey
(voir README pour la procédure). Sans clé, cette fonction renvoie "available: false"
et le reste de l'analyse continue de fonctionner normalement.

Note historique : Groq a été envisagé initialement pour cette fonctionnalité, mais
ses modèles vision (Llama 4 Scout / Maverick) ont été dépréciés courant 2026 sans
remplacement gratuit équivalent — voir https://console.groq.com/docs/deprecations.
Gemini a été retenu à la place pour son palier gratuit incluant la vision.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Dict, Optional

import requests

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger("mygoonga.gemini")

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Types MIME acceptés par l'API Gemini pour l'entrée image.
_SUPPORTED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}

_ANALYSIS_PROMPT = (
    "Tu examines une image dans le cadre d'un outil d'aide à la vérification de "
    "médias grand public (contexte : lutte contre la désinformation). Décris "
    "factuellement ce que montre l'image en 2-3 phrases maximum, puis signale "
    "UNIQUEMENT s'il existe des indices visuels concrets et observables de montage, "
    "de retouche grossière, d'incohérence de scène (ombres, perspective, proportions), "
    "ou de génération par IA. Ne te prononce jamais sur l'authenticité globale : "
    "contente-toi de décrire ce qui est observable." 
    "prête attention à des variations des tailles et style de police,"
    "adresse email non professionelle sur les offres d'emploi, image un peu floue."
    "Si tu ne vois aucun indice "
    "particulier, dis-le simplement. Réponds en français ou en anglais selon la langue dominante utilisée dans l'image, en 3-4 phrases maximum, "
    "sans mise en forme (pas de markdown, pas de liste)."
)


def is_configured() -> bool:
    return bool(settings.GEMINI_API_KEY)


def _not_configured() -> Dict[str, Any]:
    return {"available": False, "reason": "GEMINI_API_KEY n'est pas configurée."}


def _friendly_error(exc: Exception) -> str:
    """Traduit une exception technique en message compréhensible côté app.
    Le détail technique complet reste dans les logs serveur uniquement."""
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "Service d'analyse IA injoignable (problème réseau côté serveur)."
    if isinstance(exc, requests.exceptions.Timeout):
        return "Le service d'analyse IA a mis trop de temps à répondre."
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        if status == 400:
            return "Image illisible par le service d'analyse IA."
        if status in (401, 403):
            return "La clé Gemini configurée est invalide ou n'a pas les permissions requises."
        if status == 429:
            return "Quota Gemini atteint pour l'instant, réessayez plus tard."
        if status == 503:
            return "Le service d'analyse IA est temporairement surchargé."
        return f"Le service d'analyse IA a renvoyé une erreur (code {status})."
    return "Le service d'analyse IA est temporairement indisponible."


def analyze_image(image_bytes: bytes, content_type: Optional[str]) -> Dict[str, Any]:
    """Envoie l'image à Gemini pour une description + détection d'indices visuels.

    Retourne un dict :
      - {"available": False, "reason": "..."} si non configuré / échec / type non supporté
      - {"available": True, "description": "...", "flagged": bool} sinon
    """
    if not is_configured():
        return _not_configured()

    mime_type = content_type if content_type in _SUPPORTED_MIME_TYPES else "image/jpeg"

    url = f"{GEMINI_BASE_URL}/{settings.GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": _ANALYSIS_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 600,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    try:
        resp = requests.post(
            url,
            params={"key": settings.GEMINI_API_KEY},
            json=payload,
            timeout=settings.GEMINI_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates") or []
        if not candidates:
            block_reason = data.get("promptFeedback", {}).get("blockReason")
            if block_reason:
                return {"available": False, "reason": f"Image refusée par le filtre de sécurité Gemini ({block_reason})."}
            return {"available": False, "reason": "Réponse vide du service d'analyse IA."}

        parts = candidates[0].get("content", {}).get("parts", [])
        text = " ".join(p.get("text", "") for p in parts).strip()
        if not text:
            return {"available": False, "reason": "Réponse vide du service d'analyse IA."}

        finish_reason = candidates[0].get("finishReason")
        if finish_reason == "MAX_TOKENS":
            # Réponse tronquée en plein milieu : on ne l'affiche pas telle quelle
            # (une phrase coupée est trompeuse), on demande de réessayer.
            logger.warning("Réponse Gemini tronquée (MAX_TOKENS) pour le modèle %s.", settings.GEMINI_MODEL)
            return {
                "available": False,
                "reason": "La réponse de l'analyse IA a été tronquée, veuillez réessayer.",
            }

        # Heuristique simple : le prompt demande explicitement de signaler les indices
        # visuels de montage ; on détecte ici des tournures probables de signalement,
        # sans prétendre à une classification fiable — juste pour poser un flag indicatif.
        lowered = text.lower()
        flagged = any(
            kw in lowered
            for kw in [
                "indice", "incohérence", "incoherence", "montage", "retouch",
                "généré par ia", "genere par ia", "généré par intelligence artificielle",
                "manipulation", "manipulé", "manipule",
            ]
        )

        return {"available": True, "description": text, "flagged": flagged}
    except Exception as exc:
        logger.warning("Échec de l'appel à Gemini (%s) : %s", settings.GEMINI_MODEL, exc)
        return {"available": False, "reason": _friendly_error(exc)}