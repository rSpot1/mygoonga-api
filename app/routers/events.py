from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.database import Database, get_db, now_iso
from app.core.security import get_current_user
from app.models.schemas import (
    EventDetail,
    EventReportRequest,
    EventReportResponse,
    EventSummary,
    FlagOut,
    FlagRequest,
    FlagResponse,
)
from app.services.scoring import compute_aggregated_status, flag_weight, haversine_km

router = APIRouter(prefix="/events", tags=["Événements locaux"])


@router.post("/report", response_model=EventReportResponse, status_code=status.HTTP_201_CREATED)
def report_event(
    payload: EventReportRequest,
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    event = db.create(
        "events",
        {
            "reportedBy": user["id"],
            "description": payload.description,
            "city": payload.city,
            "coordinates": payload.coordinates.model_dump() if payload.coordinates else None,
            "mediaUrl": payload.mediaUrl,
            "flags": [],
            "aggregatedStatus": "insufficient_data",
        },
    )
    return EventReportResponse(eventId=event["id"], aggregatedStatus="insufficient_data")


@router.get("/nearby", response_model=list[EventSummary])
def list_nearby_events(
    lat: float = Query(...),
    lng: float = Query(...),
    radiusKm: Optional[float] = Query(None),
    _: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    from app.config import get_settings

    radius = radiusKm or get_settings().NEARBY_DEFAULT_RADIUS_KM
    events = db.list("events")
    nearby = []
    for e in events:
        coords = e.get("coordinates")
        if coords:
            distance = haversine_km(lat, lng, coords["lat"], coords["lng"])
            if distance > radius:
                continue
        nearby.append(
            EventSummary(
                eventId=e["id"],
                description=e["description"],
                city=e["city"],
                aggregatedStatus=e.get("aggregatedStatus", "insufficient_data"),
                flagCount=len(e.get("flags", [])),
            )
        )
    return nearby


@router.get("/{event_id}", response_model=EventDetail)
def get_event_detail(
    event_id: str,
    _: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    event = db.get("events", event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Événement introuvable.")
    # Anonymisation : jamais l'identité de l'auteur du flag dans l'affichage public (§11).
    flags = [
        FlagOut(
            type=f["type"],
            weight=f["weight"],
            comment=f.get("comment"),
            createdAt=f.get("createdAt", ""),
        )
        for f in event.get("flags", [])
    ]
    return EventDetail(
        eventId=event["id"],
        description=event["description"],
        aggregatedStatus=event.get("aggregatedStatus", "insufficient_data"),
        flags=flags,
    )


@router.post("/{event_id}/flag", response_model=FlagResponse, status_code=status.HTTP_201_CREATED)
def flag_event(
    event_id: str,
    payload: FlagRequest,
    user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    if payload.type not in ("confirm", "dispute", "unsure"):
        raise HTTPException(status_code=422, detail="type doit être 'confirm', 'dispute' ou 'unsure'.")

    event = db.get("events", event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Événement introuvable.")

    weight = flag_weight(user.get("role", "standard"))
    # Pour un vérificateur, le poids du flag dépend aussi de la cohérence de sa position
    # géographique récente avec la zone de l'événement (§10.4). Le MVP applique une
    # pondération simple ; le rapprochement géographique fin est laissé à la roadmap.

    flags = event.get("flags", [])
    flags.append(
        {
            "userId": user["id"],
            "type": payload.type,
            "weight": weight,
            "comment": payload.comment,
            "createdAt": now_iso(),
        }
    )

    aggregation = compute_aggregated_status(flags)
    db.update("events", event_id, {"flags": flags, "aggregatedStatus": aggregation["status"]})

    return FlagResponse(flagId=str(len(flags)), newAggregatedStatus=aggregation["status"])
