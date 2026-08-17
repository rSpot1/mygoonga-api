"""
Couche d'abstraction base de données.

Deux implémentations :
- InMemoryDatabase : dictionnaires en mémoire, aucune dépendance externe. Utilisée par défaut
  (USE_MOCK_DB=true) pour permettre de tester l'API immédiatement, sans configurer Firebase.
- FirestoreDatabase : Firestore réel, via firebase-admin. Utilisée en production.

Les deux implémentations exposent la même interface (Database), afin que les routeurs
n'aient jamais à savoir laquelle est active.
"""
from __future__ import annotations

import copy
import itertools
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import get_settings

settings = get_settings()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database(ABC):
    @abstractmethod
    def create(self, collection: str, data: Dict[str, Any], doc_id: Optional[str] = None) -> Dict[str, Any]:
        ...

    @abstractmethod
    def get(self, collection: str, doc_id: str) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    def update(self, collection: str, doc_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    def delete(self, collection: str, doc_id: str) -> None:
        ...

    @abstractmethod
    def list(
        self,
        collection: str,
        filters: Optional[List[tuple]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        ...


class InMemoryDatabase(Database):
    """Base de données en mémoire, pour le développement local et les tests rapides.
    Les données sont perdues au redémarrage du serveur."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._counter = itertools.count(1)

    def _collection(self, name: str) -> Dict[str, Dict[str, Any]]:
        return self._store.setdefault(name, {})

    def create(self, collection: str, data: Dict[str, Any], doc_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            doc_id = doc_id or str(uuid.uuid4())
            record = copy.deepcopy(data)
            record["id"] = doc_id
            record.setdefault("createdAt", now_iso())
            self._collection(collection)[doc_id] = record
            return copy.deepcopy(record)

    def get(self, collection: str, doc_id: str) -> Optional[Dict[str, Any]]:
        record = self._collection(collection).get(doc_id)
        return copy.deepcopy(record) if record else None

    def update(self, collection: str, doc_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            col = self._collection(collection)
            if doc_id not in col:
                return None
            col[doc_id].update(copy.deepcopy(data))
            col[doc_id]["updatedAt"] = now_iso()
            return copy.deepcopy(col[doc_id])

    def delete(self, collection: str, doc_id: str) -> None:
        with self._lock:
            self._collection(collection).pop(doc_id, None)

    def list(
        self,
        collection: str,
        filters: Optional[List[tuple]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        items = list(self._collection(collection).values())
        if filters:
            for field, op, value in filters:
                if op == "==":
                    items = [i for i in items if i.get(field) == value]
                elif op == "in":
                    items = [i for i in items if i.get(field) in value]
        items.sort(key=lambda i: i.get("createdAt", ""), reverse=True)
        if limit:
            items = items[:limit]
        return [copy.deepcopy(i) for i in items]


class FirestoreDatabase(Database):
    """Implémentation Firestore réelle, utilisée en production."""

    def __init__(self) -> None:
        from app.core.firebase_admin_client import get_firestore_client

        self._db = get_firestore_client()

    def create(self, collection: str, data: Dict[str, Any], doc_id: Optional[str] = None) -> Dict[str, Any]:
        data = dict(data)
        data.setdefault("createdAt", now_iso())
        if doc_id:
            ref = self._db.collection(collection).document(doc_id)
            ref.set(data)
        else:
            ref = self._db.collection(collection).document()
            data["id"] = ref.id
            ref.set(data)
        data["id"] = ref.id
        return data

    def get(self, collection: str, doc_id: str) -> Optional[Dict[str, Any]]:
        snap = self._db.collection(collection).document(doc_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        data["id"] = snap.id
        return data

    def update(self, collection: str, doc_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ref = self._db.collection(collection).document(doc_id)
        if not ref.get().exists:
            return None
        data = dict(data)
        data["updatedAt"] = now_iso()
        ref.update(data)
        return self.get(collection, doc_id)

    def delete(self, collection: str, doc_id: str) -> None:
        self._db.collection(collection).document(doc_id).delete()

    def list(
        self,
        collection: str,
        filters: Optional[List[tuple]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        query = self._db.collection(collection)
        if filters:
            for field, op, value in filters:
                query = query.where(field, op, value)
        if limit:
            query = query.limit(limit)
        docs = query.stream()
        results = []
        for d in docs:
            item = d.to_dict() or {}
            item["id"] = d.id
            results.append(item)
        return results


_db_instance: Optional[Database] = None
_db_lock = threading.Lock()


def get_db() -> Database:
    """Dépendance FastAPI : renvoie l'instance de base de données active (singleton)."""
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                if settings.USE_MOCK_DB:
                    _db_instance = InMemoryDatabase()
                else:
                    try:
                        _db_instance = FirestoreDatabase()
                    except Exception as exc:  # pragma: no cover - garde-fou de démarrage
                        raise RuntimeError(
                            "Impossible d'initialiser Firestore. Vérifiez FIREBASE_CREDENTIALS_JSON / "
                            "FIREBASE_CREDENTIALS_PATH, ou passez en USE_MOCK_DB=true pour tester "
                            f"sans Firebase. Erreur d'origine : {exc}"
                        ) from exc
    return _db_instance
