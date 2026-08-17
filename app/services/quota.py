"""
Compteur d'usage journalier générique, stocké dans la base de données existante
(collection "usage_counters"), pour plafonner un service payant/à quota (ex: appels
à l'API Gemini) indépendamment de ce que le fournisseur autorise réellement — filet
de sécurité pour ne jamais dépasser un budget prévu, même si le quota du compte
change ou est mal connu.

Fonctionne aussi bien avec InMemoryDatabase qu'avec FirestoreDatabase, puisqu'il
n'utilise que l'interface Database standard (get/create/update).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Tuple

from app.core.database import Database

COLLECTION = "usage_counters"


def _today_key(counter_name: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{counter_name}:{day}"


def check_and_increment(db: Database, counter_name: str, daily_limit: int) -> Tuple[bool, int]:
    """Vérifie si le quota journalier n'est pas atteint puis incrémente le compteur.

    Retourne (autorisé, count_apres_incrementation).
    Si autorisé=False, le compteur n'est PAS incrémenté (l'appel a été refusé,
    il ne doit pas compter dans le quota).
    """
    doc_id = _today_key(counter_name)
    existing = db.get(COLLECTION, doc_id)
    current = existing.get("count", 0) if existing else 0

    if current >= daily_limit:
        return False, current

    new_count = current + 1
    if existing:
        db.update(COLLECTION, doc_id, {"count": new_count})
    else:
        db.create(COLLECTION, {"count": new_count}, doc_id=doc_id)
    return True, new_count


def current_count(db: Database, counter_name: str) -> int:
    doc_id = _today_key(counter_name)
    existing = db.get(COLLECTION, doc_id)
    return existing.get("count", 0) if existing else 0
