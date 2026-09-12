"""RescueBase API + static UI + always-on inbox worker.  Run:  uvicorn backend.app:app --host 0.0.0.0 --port 8000"""
import json
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .models import Verification
from .pipeline import Pipeline
from .store import open_store
from .worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("rescuebase")
config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="RescueBase", version="0.2")
pipe = Pipeline(open_store())
worker = Worker(pipe) if config.INBOX_ENABLED else None
if worker:
    worker.start()
log.info("provider=%s store=%s incident=%s demo=%s inbox=%s", config.PROVIDER, pipe.store.kind, config.INCIDENT_ID,
         config.DEMO_MODE, config.INBOX_DIR if worker else "disabled")


class VerifyBody(BaseModel):
    state: Verification
    notes: str = ""


class QueryBody(BaseModel):
    question: str


class UpdateBody(BaseModel):
    text: str
    cited_event_ids: list[str] = []
    agent: str = "unknown-agent"
    model_name: str = "unknown-model"
    kind: str = "incident_update"


@app.get("/api/health")
def health():
    return pipe.health()


@app.get("/api/ingest/status")
def ingest_status():
    return worker.status() if worker else {"enabled": False, "inbox": str(config.INBOX_DIR), "running": False,
                                           "counts": {}, "recent": [], "queue_size": 0}


@app.post("/api/ingest")
def ingest(file: UploadFile = File(...), sector: str = Form(""), label: str = Form(""), simulated: str = Form(""),
           note: str = Form(""), captured_at: str = Form("")):
    data = file.file.read()
    if not data:
        raise HTTPException(400, "empty file")
    sim = None if simulated == "" else simulated.lower() in ("1", "true", "on", "yes")
    return pipe.ingest(file.filename or "upload", data, sector=sector.strip() or None, label=label.strip() or None,
                       simulated=sim, note=note.strip(), captured_at=captured_at.strip() or None,
                       captured_at_source="operator" if captured_at.strip() else None)


@app.post("/api/inbox/drop")
def inbox_drop(file: UploadFile = File(...), label: str = Form("EXERCISE"), sector: str = Form(""), note: str = Form("")):
    """Deliver a file into the always-on inbox (browser recorder, phone, another laptop). The worker does the rest."""
    if not worker:
        raise HTTPException(503, "inbox worker disabled (RESCUEBASE_INBOX_ENABLED=0)")
    data = file.file.read()
    if not data:
        raise HTTPException(400, "empty file")
    lbl = (label.strip().upper() or "UNKNOWN")
    folder = worker.inbox / lbl.lower()
    folder.mkdir(parents=True, exist_ok=True)
    src = Path(file.filename or "drop.bin")
    dest = folder / f"{src.stem}_{uuid.uuid4().hex[:6]}{src.suffix.lower()}"
    if sector.strip() or note.strip():
        dest.with_name(dest.name + ".json").write_text(json.dumps({"sector": sector.strip() or None, "note": note.strip()}), encoding="utf-8")
    part = dest.with_name(dest.name + ".part")  # written under a skipped suffix, then renamed: never seen half-written
    part.write_bytes(data)
    part.replace(dest)
    return {"path": str(dest), "label": lbl, "bytes": len(data), "note": "queued for the inbox worker (settle + scan, a few seconds)"}


@app.get("/api/events")
def events(state: str | None = None, sector: str | None = None, source_id: str | None = None,
           since: str | None = None, until: str | None = None, limit: int = 500):
    return pipe.events(state, sector, source_id, since, until, limit)


@app.get("/api/events/{event_id}")
def event(event_id: str):
    doc = pipe.store.get("events", event_id)
    if not doc:
        raise HTTPException(404, "event not found")
    return pipe.public(doc)


@app.post("/api/events/{event_id}/verify")
def verify(event_id: str, body: VerifyBody):
    return pipe.verify(event_id, body.state, body.notes)


@app.get("/api/sources")
def sources():
    return pipe.store.find("sources", {"incident_id": config.INCIDENT_ID})


@app.get("/api/sources/{source_id}")
def source(source_id: str):
    doc = pipe.store.get("sources", source_id)
    if not doc:
        raise HTTPException(404, "source not found")
    return doc


@app.get("/api/transcripts/{source_id}")
def transcript(source_id: str):
    doc = pipe.store.get("transcripts", source_id)
    if not doc:
        raise HTTPException(404, "no transcript for this source")
    return doc


@app.post("/api/query")
def query(body: QueryBody):
    return pipe.query(body.question)


@app.post("/api/sitrep")
def sitrep():
    return pipe.sitrep()


@app.get("/api/updates")
def updates(limit: int = 20):
    return pipe.store.find("updates", {"incident_id": config.INCIDENT_ID}, limit=limit)


@app.post("/api/updates")
def post_update(body: UpdateBody):
    return pipe.post_update(body.text, body.cited_event_ids, body.agent, body.model_name, body.kind)


@app.post("/api/updates/{update_id}/verify")
def verify_update(update_id: str, body: VerifyBody):
    doc = pipe.store.update("updates", update_id, {"verification_state": str(body.state), "human_notes": body.notes})
    if not doc:
        raise HTTPException(404, "update not found")
    return doc


@app.get("/api/map")
def map_info():
    bounds = [float(x) for x in config.MAP_BOUNDS.split(",")] if config.MAP_BOUNDS else None
    return {"available": (config.DATA_DIR / "map.png").exists(), "url": "/data/map.png", "bounds": bounds}


@app.post("/api/demo/reset")
def demo_reset():
    if not config.DEMO_MODE:
        raise HTTPException(403, "demo mode disabled (RESCUEBASE_DEMO=0)")
    result = pipe.demo_reset()
    if worker:
        worker.reset()
    return result


app.mount("/data", StaticFiles(directory=str(config.DATA_DIR)), name="data")
app.mount("/", StaticFiles(directory=str(config.ROOT / "frontend"), html=True), name="ui")
