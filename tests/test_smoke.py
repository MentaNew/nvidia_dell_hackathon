"""End-to-end slice with stub providers + SQLite: ingest -> event -> verify -> query. Run: python tests/test_smoke.py
Set RESCUEBASE_MONGO_URL=mongodb://127.0.0.1:27017 to exercise the Mongo store instead."""
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["RESCUEBASE_PROVIDER"] = "stub"
os.environ["RESCUEBASE_DATA_DIR"] = tempfile.mkdtemp(prefix="rescuebase-test-")
os.environ.setdefault("RESCUEBASE_MONGO_URL", "")
os.environ["RESCUEBASE_INCIDENT"] = "smoke-test"

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from backend.app import app, pipe  # noqa: E402
from backend.providers import extract_json  # noqa: E402


def test_extract_json():
    assert extract_json('<think>hmm</think>```json\n{"a": {"b": 1}}\n```') == {"a": {"b": 1}}
    assert extract_json('Sure: {"observations": []} done') == {"observations": []}


def test_slice():
    c = TestClient(app)
    pipe.store.clear("smoke-test")
    h = c.get("/api/health").json()
    assert h["backend"] == "READY" and h["local_ai"] == "STUB" and h["network"] in ("ONLINE", "OFFLINE")

    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "gray").save(buf, "PNG")
    r = c.post("/api/ingest", files={"file": ("scene.png", buf.getvalue(), "image/png")},
               data={"sector": "Sector 4", "simulated": "true"})
    assert r.status_code == 200, r.text
    ev = r.json()["events"][0]
    assert ev["verification_state"] == "AI_CANDIDATE" and ev["model_name"].startswith("stub") and ev["simulated"]
    assert c.get(f"/data{ev['source_uri'][5:]}").status_code == 200  # evidence media is served

    r = c.post("/api/ingest", files={"file": ("radio.txt", b"Team 2 reports the bridge at Sector 4 is impassable.", "text/plain")})
    assert r.status_code == 200 and r.json()["transcript"].startswith("Team 2")
    assert c.get("/api/events?sector=Sector%204").json()[0]["event_id"] == ev["event_id"]
    assert c.get("/api/events?state=HUMAN_CONFIRMED").json() == []

    r = c.post(f"/api/events/{ev['event_id']}/verify", json={"state": "HUMAN_CONFIRMED", "notes": "checked by IC"})
    assert r.json()["verification_state"] == "HUMAN_CONFIRMED" and r.json()["human_notes"] == "checked by IC"
    assert c.get("/api/events?state=AI_CANDIDATE,UNVERIFIED").json()[0]["source_name"] == "radio.txt"

    q = c.post("/api/query", json={"question": "What is unverified in sector 4?"}).json()
    assert q["retrieval"] == "keyword" and [e["source_name"] for e in q["events"]] == ["radio.txt"]
    s = c.post("/api/sitrep").json()
    assert s["event_count"] == 2 and s["source_media_bytes"] > 0
    assert c.post("/api/events/ev_nope/verify", json={"state": "HUMAN_REJECTED"}).status_code == 404
    assert c.get("/").status_code == 200 and c.post("/api/demo/reset").status_code == 200


if __name__ == "__main__":
    test_extract_json()
    test_slice()
    print("OK: smoke test passed (provider=stub, store=%s)" % pipe.store.kind)
