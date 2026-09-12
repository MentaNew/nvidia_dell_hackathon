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
    """Model-stated only. Uncalibrated: not a probability of correctness or safety."""

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
    video = "video"


class Label(StrEnum):
    """Provenance class of the input. Set by the operator (sidecar/folder/form), never by a model."""

    LIVE = "LIVE"  # captured from a live source during the incident
    REPLAY = "REPLAY"  # prerecorded real footage replayed into the system
    ARCHIVAL = "ARCHIVAL"  # real historical material
    EXERCISE = "EXERCISE"  # fictional / training input (e.g. scripted radio messages)
    SATELLITE = "SATELLITE"  # satellite imagery
    UNKNOWN = "UNKNOWN"


def _norm(v):
    return str(v).strip().upper().replace(" ", "_").replace("-", "_") if v is not None else v


class Observation(BaseModel):
    """One model-emitted observation. Deliberately small: this is the JSON schema handed to the model."""

    event_type: EventType
    observation: str = Field(description="1-2 sentences describing only what is visible or stated, preserving negation and uncertainty.")
    confidence: Confidence
    region_hint: str | None = Field(None, description="Where: position in frame or named place as stated, if any.")

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
    # Time: ordering key + explicit basis. Capture time is never faked from ingestion time.
    timestamp: str  # = captured_at when known, else ingested_at (see time_basis)
    time_basis: str = "ingest"  # "capture" | "ingest"
    captured_at: str | None = None  # when the media was captured / the report made, if known; tz only if stated
    captured_at_source: str | None = None  # "exif" | "sidecar" | "manifest" | "clip+offset"
    ingested_at: str = Field(default_factory=now_iso)  # UTC, when RescueBase processed it
    # Source / evidence
    source_type: SourceType
    source_id: str
    source_name: str  # original filename
    source_uri: str  # served path of the evidence media
    parent_source_id: str | None = None  # video frames: the clip they were sampled from
    frame_offset_s: float | None = None  # video frames: offset into the clip
    sector: str | None = None
    location: dict | None = None  # {"lat","lon","from": "exif"|"sidecar"} — never a model guess
    region_hint: str | None = None
    # Content
    event_type: EventType
    observation: str
    confidence: Confidence  # model-stated, uncalibrated
    verification_state: Verification = Verification.AI_CANDIDATE
    model_name: str
    label: Label = Label.UNKNOWN
    simulated: bool = False  # True for EXERCISE inputs — always surfaced in the UI
    related_event_ids: list[str] = []
    evidence_refs: list[str] = []
    human_notes: str = ""
    job_id: str | None = None  # inbox job that produced it, if automatic
