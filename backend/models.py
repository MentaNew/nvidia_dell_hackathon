"""Typed schemas: what models must emit (Observation) and what incident memory stores (Event)."""
import uuid
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EventType(StrEnum):
    ACCESS_BLOCKAGE = "ACCESS_BLOCKAGE"
    STRUCTURAL_DAMAGE = "STRUCTURAL_DAMAGE"
    TERRAIN_CHANGE = "TERRAIN_CHANGE"
    INFRASTRUCTURE_CONDITION = "INFRASTRUCTURE_CONDITION"
    OBJECT_OBSERVED = "OBJECT_OBSERVED"  # vehicle / person / object — never "victim"
    REPORTED_EVENT = "REPORTED_EVENT"  # something a speaker or document reports
    UNCERTAIN = "UNCERTAIN"


class Confidence(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class Verification(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    AI_CANDIDATE = "AI_CANDIDATE"
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    HUMAN_REJECTED = "HUMAN_REJECTED"
    UNKNOWN = "UNKNOWN"


class SourceType(StrEnum):
    image = "image"
    audio = "audio"
    text = "text"


def _norm(v):
    return str(v).strip().upper().replace(" ", "_").replace("-", "_") if v is not None else v


class Observation(BaseModel):
    """One model-emitted observation. Deliberately small: this is the JSON schema handed to the model."""

    event_type: EventType
    observation: str = Field(description="1-2 sentences describing only what is visible or stated.")
    confidence: Confidence
    region_hint: str | None = Field(None, description="Where: position in frame or named place, if any.")

    # Unknown labels degrade to UNCERTAIN/UNKNOWN instead of crashing an ingest mid-demo.
    @field_validator("event_type", mode="before")
    @classmethod
    def _event_type(cls, v):
        v = _norm(v)
        return v if v in EventType.__members__ else EventType.UNCERTAIN

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, v):
        v = _norm(v)
        return v if v in Confidence.__members__ else Confidence.UNKNOWN


class ObservationList(BaseModel):
    observations: list[Observation]
    scene_summary: str | None = Field(None, description="One sentence overall description.")


class Event(BaseModel):
    event_id: str = Field(default_factory=lambda: "ev_" + uuid.uuid4().hex[:10])
    incident_id: str
    timestamp: str  # when the observation happened (EXIF/source time if known, else ingest time)
    source_type: SourceType
    source_id: str
    source_name: str  # original filename
    source_uri: str  # served path of the evidence media
    sector: str | None = None
    location: dict | None = None  # {"lat": .., "lon": .., "from": "exif"}
    region_hint: str | None = None
    event_type: EventType
    observation: str
    confidence: Confidence
    verification_state: Verification = Verification.AI_CANDIDATE
    model_name: str
    simulated: bool = False  # source is simulated/illustrative — always surfaced in the UI
    related_event_ids: list[str] = []
    evidence_refs: list[str] = []
    human_notes: str = ""
    created_at: str = Field(default_factory=now_iso)
