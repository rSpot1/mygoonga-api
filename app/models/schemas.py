from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------- Utilisateurs / Auth ----------


class SyncResponse(BaseModel):
    userId: str
    role: str
    createdAt: str


class UserProfile(BaseModel):
    userId: str
    email: Optional[str] = None
    displayName: Optional[str] = None
    role: str
    verifierStatus: str
    reputationScore: int = 0
    declaredCity: Optional[str] = None
    preferredLanguage: str = "fr"


class UserProfileUpdate(BaseModel):
    displayName: Optional[str] = None
    declaredCity: Optional[str] = None
    preferredLanguage: Optional[str] = None


# ---------- Vérificateurs ----------


class VerifierApplicationCreated(BaseModel):
    applicationId: str
    status: str


class VerifierApplicationSummary(BaseModel):
    applicationId: str
    userId: str
    submittedAt: str
    metadataFlags: List[str] = Field(default_factory=list)


class VerifierApplicationDetail(BaseModel):
    applicationId: str
    cniFrontUrl: str
    cniBackUrl: str
    verificationPhotoUrl: str
    metadataFlags: List[str] = Field(default_factory=list)
    phoneNumber: str


class VerifierReviewRequest(BaseModel):
    decision: str  # "approved" | "rejected"
    reason: Optional[str] = None


class VerifierReviewResponse(BaseModel):
    applicationId: str
    status: str


# ---------- Médias ----------


class MediaAnalyzeAccepted(BaseModel):
    analysisId: str
    status: str


class MediaAnalysisResult(BaseModel):
    analysisId: str
    status: str
    coherenceFlags: List[str] = Field(default_factory=list)
    reverseMatches: List[Dict[str, Any]] = Field(default_factory=list)
    explanation: str = ""
    aiDescription: Optional[str] = None


class HumanReviewResponse(BaseModel):
    analysisId: str
    humanReviewStatus: str


# ---------- Événements locaux ----------


class Coordinates(BaseModel):
    lat: float
    lng: float


class EventReportRequest(BaseModel):
    description: str
    city: str
    coordinates: Optional[Coordinates] = None
    mediaUrl: Optional[str] = None


class EventReportResponse(BaseModel):
    eventId: str
    aggregatedStatus: str


class EventSummary(BaseModel):
    eventId: str
    description: str
    city: str
    aggregatedStatus: str
    flagCount: int


class FlagOut(BaseModel):
    type: str
    weight: int
    comment: Optional[str] = None
    createdAt: str


class EventDetail(BaseModel):
    eventId: str
    description: str
    aggregatedStatus: str
    flags: List[FlagOut] = Field(default_factory=list)


class FlagRequest(BaseModel):
    type: str  # "confirm" | "dispute" | "unsure"
    comment: Optional[str] = None


class FlagResponse(BaseModel):
    flagId: str
    newAggregatedStatus: str


# ---------- Administration ----------


class RoleUpdateRequest(BaseModel):
    role: str  # "standard" | "verifier" | "moderator" | "admin"
    reason: Optional[str] = None


class AuditLogEntry(BaseModel):
    id: str
    accessedBy: str
    accessedAt: str
    action: str
    targetCollection: str
    targetId: str