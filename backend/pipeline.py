"""Local file -> local inference -> structured, source-linked events -> incident log; retrieval + synthesis."""
import io
import json
import logging
import math
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from PIL import Image

from . import config, providers, video
from .models import Event, Label, ObservationList, SourceType, Verification, now_iso

log = logging.getLogger("rescuebase")

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}  # .webm = browser radio recordings, not video
TEXT_EXT = {".txt", ".md", ".csv", ".log"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".m4v"}
NEEDS_REVIEW = [str(Verification.AI_CANDIDATE), str(Verification.UNVERIFIED), str(Verification.UNKNOWN)]


def _dms(v) -> float:
    d, m, s = (float(x) for x in v)
    return d + m / 60 + s / 3600


def exif_meta(data: bytes) -> tuple[str | None, dict | None]:
    """(capture timestamp, {lat, lon}) from EXIF when present. Real provenance, never guessed."""
    try:
        exif = Image.open(io.BytesIO(data)).getexif()
        ts = exif.get_ifd(0x8769).get(36867) or exif.get(306)  # DateTimeOriginal, else DateTime
        ts = ts.strip().replace(":", "-", 2).replace(" ", "T") if ts else None  # no timezone in EXIF: kept naive
        gps, loc = exif.get_ifd(0x8825), None
        if gps.get(2) and gps.get(4):
            lat = _dms(gps[2]) * (-1 if gps.get(1) == "S" else 1)
            lon = _dms(gps[4]) * (-1 if gps.get(3) == "W" else 1)
            loc = {"lat": round(lat, 6), "lon": round(lon, 6), "from": "exif"}
        return ts, loc
    except Exception:
        return None, None


def _location(loc, origin: str) -> dict | None:
    """Operator-supplied coordinates only. Anything unparseable stays unknown (unpinned)."""
    try:
        if loc and loc.get("lat") is not None and loc.get("lon") is not None:
            return {"lat": float(loc["lat"]), "lon": float(loc["lon"]), "from": loc.get("from") or origin}
    except (TypeError, ValueError):
        log.warning("ignoring unparseable location %r", loc)
    return None


def _add_seconds(iso: str, seconds: float) -> str | None:
    try:
        return (datetime.fromisoformat(iso) + timedelta(seconds=seconds)).isoformat(timespec="seconds")
    except ValueError:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _line(e: dict) -> str:
    kind = {"image": "VISUAL", "video": "VISUAL", "audio": "RADIO REPORT", "text": "TEXT REPORT"}.get(e["source_type"], e["source_type"])
    when = f"captured {e['captured_at']}" if e.get("captured_at") else f"capture time unknown, ingested {e['ingested_at']}"
    loc = f"{e['location']['lat']},{e['location']['lon']}" if e.get("location") else "location unknown"
    return (f"- [{e['event_id']}] {when} | {kind} {e['source_name']} ({e['source_id']}) | {e.get('label')} | "
            f"{e.get('sector') or 'sector n/a'} | {loc} | {e['event_type']} | model conf {e['confidence']} | "
            f"{e['verification_state']} | {e['observation']}")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


class Pipeline:
    def __init__(self, store):
        self.store = store
        self.vision, self.reasoning, self.speech, self.embedding = providers.build()

    @staticmethod
    def public(doc: dict) -> dict:
        return {k: v for k, v in doc.items() if k != "embedding"}

    @staticmethod
    def _label(label) -> Label:
        raw = str(label or config.INBOX_DEFAULT_LABEL).strip().upper()
        if raw not in Label.__members__:
            log.warning("unknown label %r -> UNKNOWN", label)
            return Label.UNKNOWN
        return Label(raw)

    # ------------------------------------------------------------ ingest

    def ingest(self, filename: str, data: bytes, *, sector: str | None = None, label=None, simulated: bool | None = None,
               note: str = "", captured_at: str | None = None, captured_at_source: str | None = None, location=None,
               parent_source_id: str | None = None, frame_offset_s: float | None = None, job_id: str | None = None) -> dict:
        ext = Path(filename).suffix.lower()
        if ext not in IMAGE_EXT | AUDIO_EXT | TEXT_EXT | VIDEO_EXT:
            raise HTTPException(415, f"unsupported file type {ext!r}: image, audio, text or video")
        label = self._label(label)
        simulated = bool(simulated) if simulated is not None else label == Label.EXERCISE
        location = _location(location, "sidecar")
        source_id = "src_" + uuid.uuid4().hex[:10]
        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        stored = config.UPLOAD_DIR / f"{source_id}{ext}"
        stored.write_bytes(data)
        uri = f"/data/uploads/{stored.name}"
        common = dict(sector=sector, label=label, simulated=simulated, note=note, captured_at=captured_at,
                      captured_at_source=captured_at_source, location=location, job_id=job_id)
        if ext in VIDEO_EXT:
            return self._ingest_video(filename, data, stored, source_id, uri, **common)

        transcript = None
        if ext in IMAGE_EXT:
            stype = SourceType.image
            exif_ts, exif_loc = exif_meta(data)
            if captured_at is None and exif_ts:
                captured_at, captured_at_source = exif_ts, "exif"
            if location is None and exif_loc:
                location = exif_loc
            obs = self.vision.analyze_image(data, f"Operator context: {note}" if note else "")
            model = self.vision.name
        elif ext in AUDIO_EXT:
            stype = SourceType.audio
            transcript = self.speech.transcribe(data, filename)
            obs = self.reasoning.structured(providers.REPORT_SYSTEM, transcript, ObservationList)
            model = f"{self.speech.name} + {self.reasoning.name}"
        else:
            stype = SourceType.text
            transcript = data.decode("utf-8", errors="replace")[:8000]
            obs = self.reasoning.structured(providers.REPORT_SYSTEM, transcript, ObservationList)
            model = self.reasoning.name

        ingested_at = now_iso()
        events = [Event(incident_id=config.INCIDENT_ID, timestamp=captured_at or ingested_at,
                        time_basis="capture" if captured_at else "ingest", captured_at=captured_at,
                        captured_at_source=captured_at_source if captured_at else None, ingested_at=ingested_at,
                        source_type=stype, source_id=source_id, source_name=filename, source_uri=uri,
                        parent_source_id=parent_source_id, frame_offset_s=frame_offset_s, sector=sector, location=location,
                        region_hint=o.region_hint, event_type=o.event_type, observation=o.observation,
                        confidence=o.confidence, model_name=model, label=label, simulated=simulated,
                        evidence_refs=[uri], job_id=job_id)
                  for o in obs.observations]
        ids = [e.event_id for e in events]
        vecs = self.embedding.embed([e.observation for e in events]) if events else None
        for i, e in enumerate(events):
            doc = e.model_dump(mode="json")
            doc["related_event_ids"] = [x for x in ids if x != e.event_id]  # siblings from the same source
            if vecs:
                doc["embedding"] = vecs[i]
            self.store.insert("events", doc)
        source = {"source_id": source_id, "incident_id": config.INCIDENT_ID, "source_type": str(stype), "name": filename,
                  "uri": uri, "bytes": len(data), "timestamp": captured_at or ingested_at, "captured_at": captured_at,
                  "captured_at_source": captured_at_source if captured_at else None, "ingested_at": ingested_at,
                  "sector": sector, "location": location, "label": str(label), "simulated": simulated, "note": note,
                  "parent_source_id": parent_source_id, "frame_offset_s": frame_offset_s, "scene_summary": obs.scene_summary,
                  "model_name": model, "event_ids": ids, "job_id": job_id}
        self.store.insert("sources", source)
        if transcript is not None:
            self.store.insert("transcripts", {"source_id": source_id, "incident_id": config.INCIDENT_ID, "text": transcript,
                                              "model_name": model, "label": str(label), "simulated": simulated,
                                              "timestamp": captured_at or ingested_at})
        log.info("ingested %s as %s -> %d event(s) via %s", filename, source_id, len(ids), model)
        return {"source": source, "transcript": transcript,
                "events": [self.public(self.store.get("events", i)) for i in ids]}

    def _ingest_video(self, filename: str, data: bytes, stored: Path, source_id: str, uri: str, *, sector, label, simulated,
                      note, captured_at, captured_at_source, location, job_id) -> dict:
        """Recorded replay: sample frames at FRAME_INTERVAL_S, run each through the image path, keep the clip as parent."""
        ingested_at = now_iso()
        try:
            frames = video.extract_frames(stored)
        except Exception as e:
            raise HTTPException(422, f"frame extraction failed: {e}") from e
        if not frames:
            raise HTTPException(422, "no frames could be sampled from the clip")
        source = {"source_id": source_id, "incident_id": config.INCIDENT_ID, "source_type": "video", "name": filename,
                  "uri": uri, "bytes": len(data), "timestamp": captured_at or ingested_at, "captured_at": captured_at,
                  "captured_at_source": captured_at_source if captured_at else None, "ingested_at": ingested_at,
                  "sector": sector, "location": location, "label": str(label), "simulated": simulated, "note": note,
                  "frame_interval_s": config.FRAME_INTERVAL_S, "frames": [], "event_ids": [], "errors": [],
                  "model_name": self.vision.name, "job_id": job_id}
        self.store.insert("sources", source)  # exists before its frames so partial failures still link back
        events, stem = [], Path(filename).stem
        for offset, jpeg in frames:
            f_captured = _add_seconds(captured_at, offset) if captured_at else None
            try:
                r = self.ingest(f"{stem}@{offset:g}s.jpg", jpeg, sector=sector, label=label, simulated=simulated,
                                note=f"frame at {offset:g}s of {filename}" + (f"; {note}" if note else ""),
                                captured_at=f_captured, captured_at_source="clip+offset" if f_captured else None,
                                location=location, parent_source_id=source_id, frame_offset_s=offset, job_id=job_id)
                source["frames"].append({"offset_s": offset, "source_id": r["source"]["source_id"],
                                         "event_ids": [e["event_id"] for e in r["events"]]})
                events += r["events"]
            except Exception as e:
                log.exception("frame %gs of %s failed", offset, filename)
                source["errors"].append(f"{offset:g}s: {type(e).__name__}: {str(e)[:200]}")
        source["event_ids"] = [e["event_id"] for e in events]
        self.store.insert("sources", source)
        if not events and source["errors"]:
            raise HTTPException(500, f"all {len(frames)} sampled frames failed: {source['errors'][0]}")
        return {"source": source, "transcript": None, "events": events, "frames": len(frames), "errors": source["errors"]}

    # ------------------------------------------------------------ memory access

    def events(self, state: str | None = None, sector: str | None = None, source_id: str | None = None,
               since: str | None = None, until: str | None = None, limit: int = 500) -> list[dict]:
        filt: dict = {"incident_id": config.INCIDENT_ID}
        if state:
            filt["verification_state"] = state.split(",")
        if sector:
            filt["sector"] = sector
        if source_id:
            filt["source_id"] = source_id
        docs = self.store.find("events", filt, limit=5000)
        docs = [d for d in docs if (not since or d["timestamp"] >= since) and (not until or d["timestamp"] <= until)]
        return [self.public(d) for d in docs[:limit]]

    def verify(self, event_id: str, state: Verification, notes: str = "") -> dict:
        doc = self.store.update("events", event_id, {"verification_state": str(state), "human_notes": notes,
                                                     "verified_at": now_iso()})
        if not doc:
            raise HTTPException(404, "event not found")
        return self.public(doc)

    # ------------------------------------------------------------ query: deterministic retrieval, then synthesis

    def query(self, question: str, limit: int = 12) -> dict:
        q = question.lower()
        filt: dict = {"incident_id": config.INCIDENT_ID}
        if re.search(r"unverified|unresolved|unconfirmed|review|candidate", q):
            filt["verification_state"] = NEEDS_REVIEW
        events = self.store.find("events", filt, limit=5000)
        m = re.search(r"sector\s*([\w-]+)", q)
        if m:
            key = m.group(1)
            in_sector = [e for e in events if (e.get("sector") or "").lower().replace("sector", "").strip() == key]
            events = in_sector or events
        named = set(re.findall(r"ev_[0-9a-f]{10}", q))  # "which source supports ev_...?" -> that event first
        qvec = (self.embedding.embed([question]) or [None])[0]
        words = _words(q)

        def score(e: dict) -> float:
            if e["event_id"] in named:
                return 10.0
            if qvec and e.get("embedding"):
                return _cosine(qvec, e["embedding"])
            return len(words & _words(f"{e['observation']} {e['event_type']} {e.get('sector') or ''}")) / (len(words) or 1)

        if named:  # make sure explicitly named events are in the candidate set even if filtered out above
            events += [d for i in named if (d := self.store.get("events", i)) and d not in events]
        top = sorted(sorted(events, key=score, reverse=True)[:limit], key=lambda e: e["timestamp"])
        ctx = "\n".join(_line(e) for e in top) or "(no events in the incident log)"
        answer = self.reasoning.complete(providers.QUERY_SYSTEM, f"QUESTION: {question}\n\nEVIDENCE EVENTS (chronological):\n{ctx}")
        cited = list(dict.fromkeys(re.findall(r"ev_[0-9a-f]{10}", answer)))
        by_id = {e["event_id"]: e for e in top}
        priority = cited + [n for n in sorted(named) if n not in cited]  # cited first, then explicitly asked-about
        ordered = [by_id[c] for c in priority if c in by_id] + [e for e in top if e["event_id"] not in priority]
        return {"question": question, "answer": answer, "events": [self.public(e) for e in ordered],
                "cited": [c for c in cited if c in by_id], "uncited_claims": [c for c in cited if c not in by_id],
                "retrieval": "embedding" if qvec else "keyword", "model_name": self.reasoning.name}

    def sitrep(self) -> dict:
        states = [str(Verification.HUMAN_CONFIRMED)] + NEEDS_REVIEW
        events = self.store.find("events", {"incident_id": config.INCIDENT_ID, "verification_state": states}, limit=40)
        events.sort(key=lambda e: e["timestamp"])
        ctx = "\n".join(_line(e) for e in events) or "(no events in the incident log)"
        text = self.reasoning.complete(providers.SITREP_SYSTEM, f"INCIDENT: {config.INCIDENT_NAME}\nEVIDENCE EVENTS:\n{ctx}")
        media_bytes = sum(s.get("bytes", 0) for s in self.store.find("sources", {"incident_id": config.INCIDENT_ID}, limit=10000))
        return {"sitrep": text, "bytes": len(text.encode()), "source_media_bytes": media_bytes, "event_count": len(events),
                "model_name": self.reasoning.name, "generated_at": now_iso()}

    # ------------------------------------------------------------ agent-written updates (OpenClaw skill posts here)

    def post_update(self, text: str, cited: list[str], agent: str, model_name: str, kind: str = "incident_update") -> dict:
        """A draft, source-linked update written by a local agent. Must cite existing events; stays AI_CANDIDATE."""
        ids = list(dict.fromkeys([*cited, *re.findall(r"ev_[0-9a-f]{10}", text)]))
        known = [i for i in ids if self.store.get("events", i)]
        unknown = [i for i in ids if i not in known]
        if not known:
            raise HTTPException(422, "an update must cite at least one existing event id like [ev_1a2b3c4d5e]")
        doc = {"update_id": "upd_" + uuid.uuid4().hex[:10], "incident_id": config.INCIDENT_ID, "kind": kind,
               "text": text.strip()[:4000], "cited_event_ids": known, "unknown_ids": unknown, "agent": agent,
               "model_name": model_name, "verification_state": str(Verification.AI_CANDIDATE), "human_notes": "",
               "timestamp": now_iso()}
        self.store.insert("updates", doc)
        log.info("update %s posted by %s (%s): %d cited, %d unknown ids", doc["update_id"], agent, model_name, len(known), len(unknown))
        return doc

    # ------------------------------------------------------------ ops

    def health(self) -> dict:
        provs = {"vision": self.vision, "reasoning": self.reasoning, "speech": self.speech, "embedding": self.embedding}
        with ThreadPoolExecutor(4) as ex:
            endpoint = dict(zip(provs, ex.map(lambda p: p.health(), provs.values())))
        detail = {k: {"endpoint": endpoint[k], "model": p.name, **providers.LAST[k]} for k, p in provs.items()}
        v = detail["vision"]
        # Endpoint availability != processing: PROVEN only after a real successful run in this process.
        if endpoint["vision"] == "STUB":
            inference = "STUB"
        elif endpoint["vision"] != "READY":
            inference = "UNAVAILABLE"
        elif v["last_success"] is None:
            inference = "ENDPOINT_UP_UNPROVEN"
        elif v["last_error_at"] and v["last_error_at"] > v["last_success"]:
            inference = "DEGRADED"
        else:
            inference = "PROVEN"
        return {"backend": "READY", "store": self.store.kind, "store_status": self.store.health(), "providers": detail,
                "inference": inference, "inference_last_success": v["last_success"], "network": providers.network_state(),
                "incident": {"id": config.INCIDENT_ID, "name": config.INCIDENT_NAME}, "demo_mode": config.DEMO_MODE,
                "time": now_iso()}

    def demo_reset(self) -> dict:
        """Wipe the incident (events, sources, transcripts, jobs) and re-ingest data/demo/ through the live pipeline."""
        self.store.clear(config.INCIDENT_ID)
        for f in config.UPLOAD_DIR.glob("*"):
            if f.name != ".gitkeep":
                f.unlink()
        manifest: dict = {}
        mf = config.DEMO_DIR / "manifest.json"
        if mf.exists():
            manifest = {m["file"]: m for m in json.loads(mf.read_text(encoding="utf-8"))}
        results = []
        files = sorted(config.DEMO_DIR.iterdir()) if config.DEMO_DIR.exists() else []
        for f in files:
            if f.is_dir() or f.suffix.lower() in {".md", ".json"}:
                continue
            m = manifest.get(f.name, {})
            try:
                r = self.ingest(f.name, f.read_bytes(), sector=m.get("sector"), label=m.get("label"), simulated=m.get("simulated"),
                                note=m.get("note", ""), captured_at=m.get("captured_at") or m.get("timestamp"),
                                captured_at_source="manifest", location=m.get("location"))
                results.append({"file": f.name, "events": len(r["events"])})
            except Exception as e:
                log.exception("demo ingest failed for %s", f.name)
                results.append({"file": f.name, "error": str(e)})
        return {"ingested": results}
