"""
Logique métier du Pilier 2 (§7.5 du cahier des charges) : calcul du statut agrégé
d'un événement local à partir des flags posés par les utilisateurs standards et vérificateurs.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from app.config import get_settings

settings = get_settings()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def flag_weight(role: str) -> int:
    return settings.FLAG_WEIGHT_VERIFIER if role == "verifier" else settings.FLAG_WEIGHT_STANDARD


def compute_score(flags: List[Dict[str, Any]]) -> int:
    score = 0
    for f in flags:
        weight = f.get("weight", settings.FLAG_WEIGHT_STANDARD)
        if f["type"] == "confirm":
            score += weight
        elif f["type"] == "dispute":
            score -= weight
        # "unsure" ne modifie pas le score numérique, mais compte dans le total de flags
    return score


def compute_aggregated_status(flags: List[Dict[str, Any]]) -> Dict[str, Any]:
    score = compute_score(flags)
    total_flags = len(flags)
    confirmations = sum(1 for f in flags if f["type"] == "confirm")
    disputes = sum(1 for f in flags if f["type"] == "dispute")
    unsure = sum(1 for f in flags if f["type"] == "unsure")

    if total_flags < 2:
        label = "insufficient_data"
    elif score >= settings.SCORE_THRESHOLD_RELIABLE:
        label = "likely_reliable"
    elif score <= settings.SCORE_THRESHOLD_DOUBTFUL:
        label = "likely_doubtful"
    else:
        label = "insufficient_data"

    return {
        "status": label,
        "score": score,
        "totalFlags": total_flags,
        "confirmations": confirmations,
        "disputes": disputes,
        "unsure": unsure,
    }
