"""RescueBase API + static UI.  Run:  uvicorn backend.app:app --host 0.0.0.0 --port 8000"""
import logging

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .models import Verification
from .pipeline import Pipeline
from .store import open_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("rescuebase")
config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="RescueBase", version="0.1")
pipe = Pipeline(open_store())
log.info("provider=%s store=%s incident=%s demo=%s", config.PROVIDER, pipe.store.kind, config.INCIDENT_ID, config.DEMO_MODE)


class VerifyBody(BaseModel):
    state: Verification
    notes: str = ""


class QueryBody(BaseModel):
    question: str


@app.get("/api/health")
def health():
    return pipe.health()


@app.post("/api/ingest")
def ingest(file: UploadFile = File(...), sector: str = Form(""), simulated: bool = Form(False), note: str = Form("")):
    data = file.file.read()
    if not data:
        raise HTTPException(400, "empty file")
    return pipe.ingest(file.filename or "upload", data, sector=sector.strip() or None, simulated=simulated, note=note.strip())


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


@app.get("/api/map")
def map_info():
    bounds = [float(x) for x in config.MAP_BOUNDS.split(",")] if config.MAP_BOUNDS else None
    return {"available": (config.DATA_DIR / "map.png").exists(), "url": "/data/map.png", "bounds": bounds}


@app.post("/api/demo/reset")
def demo_reset():
    if not config.DEMO_MODE:
        raise HTTPException(403, "demo mode disabled (RESCUEBASE_DEMO=0)")
    return pipe.demo_reset()


app.mount("/data", StaticFiles(directory=str(config.DATA_DIR)), name="data")
app.mount("/", StaticFiles(directory=str(config.ROOT / "frontend"), html=True), name="ui")
