"""
Intégration des modèles Hugging Face via les Inference Providers
(https://router.huggingface.co/hf-inference). Aucun modèle n'est téléchargé ni exécuté
localement : tout passe par un appel HTTP authentifié avec HUGGINGFACE_API_TOKEN.

Note historique : l'ancien endpoint "api-inference.huggingface.co" (Serverless
Inference API) a été définitivement fermé par Hugging Face fin 2025, remplacé par
les "Inference Providers" via router.huggingface.co. Ce fichier utilise la nouvelle
adresse ; si Hugging Face fait à nouveau évoluer ses endpoints, seule la constante
HF_BASE_URL ci-dessous doit être mise à jour.

Si le token n'est pas configuré, chaque fonction renvoie un résultat "available: false"
plutôt que de lever une exception : l'analyse de cohérence reste utilisable (métadonnées + ELA),
seule la recherche d'image inversée (fonctionnalité "nice to have" du MVP) est désactivée.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

import requests

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger("mygoonga.huggingface")

HF_BASE_URL = "https://router.huggingface.co/hf-inference/models"


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {settings.HUGGINGFACE_API_TOKEN}"}


def is_configured() -> bool:
    return bool(settings.HUGGINGFACE_API_TOKEN)


def _not_configured(reason: str = "HUGGINGFACE_API_TOKEN n'est pas configuré.") -> Dict[str, Any]:
    return {"available": False, "reason": reason}


def _friendly_hf_error(exc: Exception, model_label: str) -> str:
    """Traduit une exception technique (DNS, timeout, quota HF...) en message
    compréhensible pour l'utilisateur final. Le détail technique complet est
    toujours conservé dans les logs serveur (voir appels logger.warning ci-dessous),
    jamais affiché tel quel dans l'application."""
    if isinstance(exc, requests.exceptions.ConnectionError):
        return f"Service {model_label} injoignable (problème réseau côté serveur)."
    if isinstance(exc, requests.exceptions.Timeout):
        return f"Le service {model_label} a mis trop de temps à répondre."
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        if status == 401:
            return "Le jeton Hugging Face configuré est invalide ou a expiré."
        if status == 403:
            return (
                "Le jeton Hugging Face n'a pas la permission d'appeler les Inference "
                "Providers. Créez un nouveau token sur huggingface.co/settings/tokens "
                "(type \"Read\", ou \"Fine-grained\" avec la permission \"Make calls to "
                "Inference Providers\" cochée)."
            )
        if status == 402:
            return "Quota Hugging Face dépassé pour ce jeton."
        if status == 404:
            return f"Le modèle {model_label} n'est plus disponible sur Hugging Face."
        if status == 503:
            return f"Le modèle {model_label} est en cours de chargement, réessayez dans quelques instants."
        return f"Le service {model_label} a renvoyé une erreur (code {status})."
    return f"Le service {model_label} est temporairement indisponible."


def image_embedding(image_bytes: bytes) -> Dict[str, Any]:
    """Calcule un vecteur d'embedding d'image via un modèle CLIP, utilisé pour la
    recherche d'image inversée (comparaison avec les médias déjà soumis)."""
    if not is_configured():
        return _not_configured()

    url = f"{HF_BASE_URL}/{settings.HF_CLIP_MODEL}"
    try:
        resp = requests.post(
            url,
            headers=_headers(),
            data=image_bytes,
            timeout=settings.HF_TIMEOUT_SECONDS,
            params={"wait_for_model": "true"},
        )
        resp.raise_for_status()
        data = resp.json()
        # Selon le modèle, la sortie peut être directement un vecteur, ou une liste imbriquée.
        vector = _flatten_vector(data)
        return {"available": True, "vector": vector}
    except Exception as exc:
        logger.warning("Échec de l'appel au modèle CLIP (%s) : %s", settings.HF_CLIP_MODEL, exc)
        return {"available": False, "reason": _friendly_hf_error(exc, "de recherche d'image inversée")}


def _flatten_vector(data: Any) -> List[float]:
    if isinstance(data, list):
        flat = data
        while isinstance(flat, list) and len(flat) == 1 and isinstance(flat[0], list):
            flat = flat[0]
        if isinstance(flat, list) and all(isinstance(x, (int, float)) for x in flat):
            return [float(x) for x in flat]
        # moyenne sur la dernière dimension si sortie type [tokens, dims]
        try:
            import numpy as np

            arr = np.array(data)
            return arr.mean(axis=tuple(range(arr.ndim - 1))).tolist()
        except Exception:
            return []
    return []


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def reverse_image_search(
    image_bytes: bytes, known_embeddings: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Recherche d'image inversée simplifiée pour le MVP : compare l'embedding CLIP de
    l'image soumise aux embeddings des médias déjà analysés dans la base (au lieu d'un
    index inversé externe). Renvoie les correspondances au-dessus du seuil configuré."""
    embedding_result = image_embedding(image_bytes)
    if not embedding_result.get("available"):
        return embedding_result

    vector = embedding_result["vector"]
    matches = []
    for entry in known_embeddings:
        sim = cosine_similarity(vector, entry.get("vector", []))
        if sim >= settings.REVERSE_MATCH_SIMILARITY_THRESHOLD:
            matches.append(
                {
                    "analysisId": entry.get("analysisId"),
                    "similarity": round(sim, 4),
                    "submittedAt": entry.get("submittedAt"),
                }
            )
    matches.sort(key=lambda m: m["similarity"], reverse=True)
    return {"available": True, "vector": vector, "matches": matches[:5]}


def transcribe_audio(audio_bytes: bytes) -> Dict[str, Any]:
    """Transcription audio via un modèle type Whisper (module audio, nice-to-have)."""
    if not is_configured():
        return _not_configured()

    url = f"{HF_BASE_URL}/{settings.HF_WHISPER_MODEL}"
    try:
        resp = requests.post(
            url,
            headers=_headers(),
            data=audio_bytes,
            timeout=settings.HF_TIMEOUT_SECONDS,
            params={"wait_for_model": "true"},
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("text") if isinstance(data, dict) else None
        return {"available": True, "text": text}
    except Exception as exc:
        logger.warning("Échec de l'appel au modèle de transcription (%s) : %s", settings.HF_WHISPER_MODEL, exc)
        return {"available": False, "reason": _friendly_hf_error(exc, "de transcription audio")}


def text_similarity(text_a: str, text_b: str) -> Dict[str, Any]:
    """Similarité sémantique de texte via sentence-transformers, utile pour rapprocher
    deux signalements d'événements qui décrivent probablement le même fait."""
    if not is_configured():
        return _not_configured()

    url = f"{HF_BASE_URL}/{settings.HF_SENTENCE_MODEL}"
    payload = {"inputs": {"source_sentence": text_a, "sentences": [text_b]}}
    try:
        resp = requests.post(url, headers=_headers(), json=payload, timeout=settings.HF_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        score = data[0] if isinstance(data, list) and data else None
        return {"available": True, "similarity": score}
    except Exception as exc:
        logger.warning("Échec de l'appel au modèle de similarité de texte (%s) : %s", settings.HF_SENTENCE_MODEL, exc)
        return {"available": False, "reason": _friendly_hf_error(exc, "de similarité de texte")}