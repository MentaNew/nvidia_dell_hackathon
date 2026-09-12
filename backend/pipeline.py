"""Local file -> local inference -> structured events -> incident memory; deterministic retrieval + synthesis."""
import io
import json
import logging
import math
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import HTTPException
from PIL import Image

from . import config, providers
from .models import Event, ObservationList, SourceType, Verification, now_iso

log = logging.getLogger("rescuebase")

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}
TEXT_EXT = {".txt", ".md", ".csv", ".log"}
NEEDS_REVIEW = [str(Verification.AI_CANDIDATE), str(Verification.UNVERIFIED), str(Verification.UNKNOWN)]


def _dms(v) -> float:
    d, m, s = (float(x) for x in v)
    return d + m / 60 + s / 3600


def exif_meta(data: bytes) -> tuple[str | None, dict | None]:
    """(ISO timestamp, {lat, lon}) from EXIF when present. Real provenance, never guessed."""
    try:
        exif = Image.open(io.BytesIO(data)).getexif()
        ts = exif.get_ifd(0x8769).get(36867) or exif.get(306)  # DateTimeOriginal, else DateTime
        ts = ts.strip().replace(":", "-", 2).replace(" ", "T") if ts else None
        gps, loc = exif.get_ifd(0x8825), None
        if gps.get(2) and gps.get(4):
            lat = _dms(gps[2]) * (-1 if gps.get(1) == "S" else 1)
            lon = _dms(gps[4]) * (-1 if gps.get(3) == "W" else 1)
            loc = {"lat": round(lat, 6), "lon": round(lon, 6), "from": "exif"}
        return ts, loc
    except Exception:
        return None, None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _line(e: dict) -> str:
    sim = " | SIMULATED" if e.get("simulated") else ""
    sector = e.get("sector") or "sector n/a"
    return (f"- [{e['event_id']}] {e['timestamp']} | {e['source_type']} {e['source_name']} | {sector}"
            f" | {e['event_type']} | conf {e['confidence']} | {e['verification_state']}{sim} | {e['observation']}")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


class Pipeline:
    def __init__(self, store):
        self.store = store
        self.vision, self.reasoning, self.speech, self.embedding = providers.build()

    @staticmethod
    def public(doc: dict) -> dict:
        return {k: v for k, v in doc.items() if k != "embedding"}

    # ------------------------------------------------------------ ingest

    def ingest(self, filename: str, data: bytes, sector: str | None = None, simulated: bool = False,
               note: str = "", timestamp: str | None = None) -> dict:
        ext = Path(filename).suffix.lower()
        if ext not in IMAGE_EXT | AUDIO_EXT | TEXT_EXT:
            raise HTTPException(415, f"unsupported file type {ext!r}: images, audio or text. Video: extract frames first.")
        source_id = "src_" + uuid.uuid4().hex[:10]
        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        stored = config.UPLOAD_DIR / f"{source_id}{ext}"
        stored.write_bytes(data)
        uri = f"/data/uploads/{stored.name}"
        location, transcript, ts = None, None, timestamp

        if ext in IMAGE_EXT:
            stype = SourceType.image
            exif_ts, location = exif_meta(data)
            ts = ts or exif_ts
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
        ts = ts or now_iso()

        events = [Event(incident_id=config.INCIDENT_ID, timestamp=ts, source_type=stype, source_id=source_id,
                        source_name=filename, source_uri=uri, sector=sector, location=location,
                        region_hint=o.region_hint, event_type=o.event_type, observation=o.observation,
                        confidence=o.confidence, model_name=model, simulated=simulated, evidence_refs=[uri])
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
                  "uri": uri, "bytes": len(data), "timestamp": ts, "sector": sector, "simulated": simulated, "note": note,
                  "scene_summary": obs.scene_summary, "model_name": model, "event_ids": ids, "created_at": now_iso()}
        self.store.insert("sources", source)
        if transcript is not None:
            self.store.insert("transcripts", {"source_id": source_id, "incident_id": config.INCIDENT_ID, "text": transcript,
                                              "model_name": model, "simulated": simulated, "timestamp": ts})
        log.info("ingested %s as %s -> %d event(s) via %s", filename, source_id, len(ids), model)
        return {"source": source, "transcript": transcript,
                "events": [self.public(self.store.get("events", i)) for i in ids]}

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
        qvec = (self.embedding.embed([question]) or [None])[0]
        words = _words(q)

        def score(e: dict) -> float:
            if qvec and e.get("embedding"):
                return _cosine(qvec, e["embedding"])
            return len(words & _words(f"{e['observation']} {e['event_type']} {e.get('sector') or ''}")) / (len(words) or 1)

        top = sorted(sorted(events, key=score, reverse=True)[:limit], key=lambda e: e["timestamp"])
        ctx = "\n".join(_line(e) for e in top) or "(no events in incident memory)"
        answer = self.reasoning.complete(providers.QUERY_SYSTEM, f"QUESTION: {question}\n\nEVIDENCE EVENTS (chronological):\n{ctx}")
        cited = list(dict.fromkeys(re.findall(r"ev_[0-9a-f]{10}", answer)))
        by_id = {e["event_id"]: e for e in top}
        ordered = [by_id[c] for c in cited if c in by_id] + [e for e in top if e["event_id"] not in cited]
        return {"question": question, "answer": answer, "events": [self.public(e) for e in ordered],
                "retrieval": "embedding" if qvec else "keyword", "model_name": self.reasoning.name}

    def sitrep(self) -> dict:
        states = [str(Verification.HUMAN_CONFIRMED)] + NEEDS_REVIEW
        events = self.store.find("events", {"incident_id": config.INCIDENT_ID, "verification_state": states}, limit=40)
        events.sort(key=lambda e: e["timestamp"])
        ctx = "\n".join(_line(e) for e in events) or "(no events in incident memory)"
        text = self.reasoning.complete(providers.SITREP_SYSTEM, f"INCIDENT: {config.INCIDENT_NAME}\nEVIDENCE EVENTS:\n{ctx}")
        media_bytes = sum(s.get("bytes", 0) for s in self.store.find("sources", {"incident_id": config.INCIDENT_ID}, limit=10000))
        return {"sitrep": text, "bytes": len(text.encode()), "source_media_bytes": media_bytes, "event_count": len(events),
                "model_name": self.reasoning.name, "generated_at": now_iso()}

    # ------------------------------------------------------------ ops

    def health(self) -> dict:
        provs = {"vision": self.vision, "reasoning": self.reasoning, "speech": self.speech, "embedding": self.embedding}
        with ThreadPoolExecutor(4) as ex:
            status = dict(zip(provs, ex.map(lambda p: p.health(), provs.values())))
        core = [status["vision"], status["reasoning"]]
        if all(s == "READY" for s in core):
            local_ai = "OPERATIONAL"
        elif all(s == "STUB" for s in status.values()):
            local_ai = "STUB"
        elif any(s == "READY" for s in core):
            local_ai = "DEGRADED"
        else:
            local_ai = "UNAVAILABLE"
        return {"backend": "READY", "store": self.store.kind, "store_status": self.store.health(),
                "providers": status, "models": {k: p.name for k, p in provs.items()}, "local_ai": local_ai,
                "network": providers.network_state(), "incident": {"id": config.INCIDENT_ID, "name": config.INCIDENT_NAME},
                "demo_mode": config.DEMO_MODE, "time": now_iso()}

    def demo_reset(self) -> dict:
        """Wipe the incident and re-ingest data/demo/ through the live pipeline. Nothing is fabricated."""
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
                r = self.ingest(f.name, f.read_bytes(), sector=m.get("sector"), simulated=m.get("simulated", False),
                                note=m.get("note", ""), timestamp=m.get("timestamp"))
                results.append({"file": f.name, "events": len(r["events"])})
            except Exception as e:
                log.exception("demo ingest failed for %s", f.name)
                results.append({"file": f.name, "error": str(e)})
        return {"ingested": results}
