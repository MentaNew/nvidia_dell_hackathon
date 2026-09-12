"""Stub-provider tests (no GPU): the end-to-end slice, the inbox worker, video frame sampling and provenance rules.
Run: python tests/test_smoke.py      (set RESCUEBASE_MONGO_URL=mongodb://127.0.0.1:27017 to exercise the Mongo store)
Real-model tests live in tests/test_real.py."""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["RESCUEBASE_PROVIDER"] = "stub"
os.environ["RESCUEBASE_DATA_DIR"] = tempfile.mkdtemp(prefix="rescuebase-test-")
os.environ.setdefault("RESCUEBASE_MONGO_URL", "")
os.environ["RESCUEBASE_INCIDENT"] = "smoke-test"
os.environ["RESCUEBASE_INBOX_ENABLED"] = "0"  # tests drive their own Worker instances synchronously

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from backend import config  # noqa: E402
from backend.app import app, pipe  # noqa: E402
from backend.providers import extract_json  # noqa: E402
from backend.worker import Worker  # noqa: E402

INCIDENT = "smoke-test"
c = TestClient(app)


def png(color="gray", size=(64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def settle(root: Path, age_s: float = 10, keep_fresh: str = "partial.png") -> None:
    """Age files so the worker treats them as settled; keep_fresh stays 'still being written'."""
    old = time.time() - age_s
    for f in root.rglob("*"):
        if f.name != keep_fresh:
            os.utime(f, (old, old))


def test_extract_json():
    assert extract_json('<think>hmm</think>```json\n{"a": {"b": 1}}\n```') == {"a": {"b": 1}}
    assert extract_json('Sure: {"observations": []} done') == {"observations": []}


def test_slice():
    pipe.store.clear(INCIDENT)
    h = c.get("/api/health").json()
    assert h["backend"] == "READY" and h["inference"] == "STUB" and h["network"] in ("ONLINE", "OFFLINE")
    assert h["providers"]["vision"]["last_success"] is None  # stubs never claim a real run

    r = c.post("/api/ingest", files={"file": ("scene.png", png(), "image/png")}, data={"sector": "Sector 4", "label": "EXERCISE"})
    assert r.status_code == 200, r.text
    ev = r.json()["events"][0]
    assert ev["verification_state"] == "AI_CANDIDATE" and ev["model_name"].startswith("stub")
    assert ev["label"] == "EXERCISE" and ev["simulated"] is True
    assert ev["captured_at"] is None and ev["time_basis"] == "ingest" and ev["timestamp"] == ev["ingested_at"]
    assert ev["location"] is None
    assert c.get(f"/data{ev['source_uri'][5:]}").status_code == 200  # evidence media is served

    r = c.post("/api/ingest", files={"file": ("radio.txt", b"Team 2 reports the bridge at Sector 4 is impassable.", "text/plain")},
               data={"captured_at": "2026-09-12T08:40:00", "label": "REPLAY"})
    assert r.status_code == 200 and r.json()["transcript"].startswith("Team 2")
    ev2 = r.json()["events"][0]
    assert ev2["captured_at"] == "2026-09-12T08:40:00" and ev2["captured_at_source"] == "operator" and ev2["time_basis"] == "capture"
    assert ev2["simulated"] is False and ev2["label"] == "REPLAY"
    assert c.get("/api/events?sector=Sector%204").json()[0]["event_id"] == ev["event_id"]
    assert c.get("/api/events?state=HUMAN_CONFIRMED").json() == []

    r = c.post(f"/api/events/{ev['event_id']}/verify", json={"state": "HUMAN_CONFIRMED", "notes": "checked by ops lead"})
    assert r.json()["verification_state"] == "HUMAN_CONFIRMED" and r.json()["human_notes"] == "checked by ops lead"
    assert c.get("/api/events?state=AI_CANDIDATE,UNVERIFIED").json()[0]["source_name"] == "radio.txt"

    q = c.post("/api/query", json={"question": "What is unverified in sector 4?"}).json()
    assert q["retrieval"] == "keyword" and [e["source_name"] for e in q["events"]] == ["radio.txt"]
    q = c.post("/api/query", json={"question": f"Which source supports {ev['event_id']}?"}).json()
    assert q["events"][0]["event_id"] == ev["event_id"]
    s = c.post("/api/sitrep").json()
    assert s["event_count"] == 2 and s["source_media_bytes"] > 0

    # agent-written updates must cite existing events and stay drafts
    body = {"text": f"NEW RADIO/TEXT REPORTS\n- bridge reported impassable, unconfirmed [{ev2['event_id']}]", "agent": "openclaw/main", "model_name": "vllm/qwen3-vl"}
    u = c.post("/api/updates", json=body).json()
    assert u["cited_event_ids"] == [ev2["event_id"]] and u["verification_state"] == "AI_CANDIDATE" and u["agent"] == "openclaw/main"
    assert c.post("/api/updates", json={"text": "nothing cited [ev_0000000000]", "agent": "x", "model_name": "y"}).status_code == 422
    assert c.get("/api/updates").json()[0]["update_id"] == u["update_id"]
    assert c.post(f"/api/updates/{u['update_id']}/verify", json={"state": "HUMAN_CONFIRMED"}).json()["verification_state"] == "HUMAN_CONFIRMED"
    assert c.post("/api/events/ev_nope/verify", json={"state": "HUMAN_REJECTED"}).status_code == 404
    assert c.post("/api/ingest", files={"file": ("x.exe", b"nope", "application/octet-stream")}).status_code == 415
    assert c.get("/").status_code == 200 and c.post("/api/demo/reset").status_code == 200
    assert c.get("/api/events").json() == []


def test_worker():
    pipe.store.clear(INCIDENT)
    inbox = Path(tempfile.mkdtemp(prefix="rescuebase-inbox-"))
    (inbox / "exercise").mkdir()
    (inbox / "exercise" / "drone_a.png").write_bytes(png())
    report = b"Team 2: the bridge at Sector 4 is NOT collapsed; the access road is blocked by debris."
    (inbox / "report1.txt").write_bytes(report)
    (inbox / "report1_copy.txt").write_bytes(report)  # identical bytes under a new name: duplicate, not a new source
    (inbox / "report2.txt").write_bytes(b"Team 3: intake gate 2 is open, water is not rising.")  # conflicting-style second report
    (inbox / "report2.txt.json").write_text(json.dumps({"sector": "Sector 2", "label": "REPLAY", "captured_at": "2026-09-12T08:00:00",
                                                        "location": {"lat": 27.7, "lon": 85.3}}))
    (inbox / "bad.png").write_bytes(b"not an image at all")  # fails in the vision path
    (inbox / "partial.png").write_bytes(png("red"))  # still being written: mtime stays fresh, must not be picked up
    settle(inbox)

    w = Worker(pipe, inbox=inbox, settle_s=1, retries=0, concurrency=1)
    assert w.scan_once() == 0  # first pass only records sizes (settle detection)
    assert w.scan_once() == 4  # drone_a, report1, report2, bad; the copy is deduplicated, partial.png not settled
    assert w.drain() == 4
    jobs = {j["name"]: j for j in pipe.store.find("jobs", {"incident_id": INCIDENT}, limit=100)}
    assert len(jobs) == 4
    assert jobs["drone_a.png"]["status"] == "completed" and jobs["report2.txt"]["status"] == "completed"
    assert jobs["bad.png"]["status"] == "failed" and jobs["bad.png"]["attempts"] == 1 and jobs["bad.png"]["error"]
    assert jobs["report1.txt"]["duplicate_paths"] == [str(inbox / "report1_copy.txt")]

    evs = {e["source_name"]: e for e in c.get("/api/events").json()}
    assert set(evs) == {"drone_a.png", "report1.txt", "report2.txt"}  # one failed input did not block the others
    a, r1, r2 = evs["drone_a.png"], evs["report1.txt"], evs["report2.txt"]
    assert a["label"] == "EXERCISE" and a["simulated"] and a["job_id"] == jobs["drone_a.png"]["job_id"]
    assert "NOT collapsed" in r1["observation"] and r1["location"] is None and r1["time_basis"] == "ingest"
    assert r2["label"] == "REPLAY" and r2["sector"] == "Sector 2" and r2["captured_at"] == "2026-09-12T08:00:00"
    assert r2["captured_at_source"] == "sidecar" and r2["location"] == {"lat": 27.7, "lon": 85.3, "from": "sidecar"}
    assert r1["source_id"] != r2["source_id"]  # separate reports stay separate sources

    # restart: a fresh worker over the same inbox must not re-ingest anything
    w2 = Worker(pipe, inbox=inbox, settle_s=1, retries=0)
    w2.scan_once()
    assert w2.scan_once() == 0 and w2.drain() == 0
    assert len(c.get("/api/events").json()) == 3

    # failed-input recovery: replacing the bad file (new content hash) is a new job that succeeds
    (inbox / "bad.png").write_bytes(png("blue"))
    settle(inbox)
    w2.scan_once()
    assert w2.scan_once() == 1 and w2.drain() == 1
    assert len(c.get("/api/events").json()) == 4
    st = w2.status()
    assert st["counts"]["completed"] == 4 and st["counts"]["failed"] == 1 and st["queue_size"] == 0
    assert c.get("/api/ingest/status").json()["enabled"] is False  # app-level worker disabled in tests

    # bounded retry: with retries=1 a failure is scheduled once more, then final
    (inbox / "bad2.png").write_bytes(b"still not an image")
    settle(inbox)
    w3 = Worker(pipe, inbox=inbox, settle_s=1, retries=1)
    w3.scan_once()
    assert w3.scan_once() == 1 and w3.drain() == 1
    j = pipe.store.get("jobs", "job_" + __import__("hashlib").sha256(b"still not an image").hexdigest()[:16])
    assert j["status"] == "retrying" and j["attempts"] == 1
    time.sleep(2.5)  # retry timer (2**1 s) requeues it
    assert w3.drain() == 1
    j = pipe.store.get("jobs", j["job_id"])
    assert j["status"] == "failed" and j["attempts"] == 2


def test_audio_paths():
    """WAV goes straight to the speech provider; browser/phone formats are transcoded to WAV first (needs ffmpeg)."""
    import wave
    from backend.video import ffmpeg_exe

    pipe.store.clear(INCIDENT)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000), w.writeframes(b"\x00\x00" * 16000)
    r = c.post("/api/ingest", files={"file": ("radio_a.wav", buf.getvalue(), "audio/wav")}, data={"label": "EXERCISE", "sector": "Sector 3"})
    assert r.status_code == 200, r.text
    ev = r.json()["events"][0]
    assert ev["source_type"] == "audio" and ev["simulated"] and "radio_a.wav" in r.json()["transcript"]
    assert c.get(f"/api/transcripts/{ev['source_id']}").json()["text"] == r.json()["transcript"]
    exe = ffmpeg_exe()
    if not exe:
        print("SKIP webm transcode test: no ffmpeg")
        return
    clip = Path(tempfile.mkdtemp(prefix="rescuebase-audio-")) / "msg.webm"
    subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "libopus", str(clip)], check=True)
    r = c.post("/api/ingest", files={"file": ("msg.webm", clip.read_bytes(), "audio/webm")}, data={"label": "EXERCISE"})
    assert r.status_code == 200, r.text
    assert "msg.wav" in r.json()["transcript"]  # the stub echoes the (transcoded) filename it received
    assert c.get(r.json()["events"][0]["source_uri"]).status_code == 200  # the original recording stays the evidence


def test_telemetry():
    """Telemetry handling only: the nvidia-smi parser and the unavailable path. Actual GB10 readings are NOT TESTED here."""
    from backend import telemetry

    g = telemetry.parse_nvidia_smi("NVIDIA GB10, 580.65.06, 41234, 122880, 37, 52, 41.2")
    assert g["name"] == "NVIDIA GB10" and g["memory.used"] == 41234 and g["memory.total"] == 122880 and g["power.draw"] == 41.2
    assert telemetry.gb10_detected(g) is True
    g2 = telemetry.parse_nvidia_smi("NVIDIA GB10, 580.65.06, [N/A], [N/A], 0, [N/A], [N/A]")
    assert g2["memory.used"] is None and g2["utilization.gpu"] == 0
    assert telemetry.gb10_detected({"name": "Intel Arc"}) is False and telemetry.gb10_detected(None) is False
    try:
        telemetry.parse_nvidia_smi("garbage")
        assert False, "expected ValueError"
    except ValueError:
        pass

    t = c.get("/api/telemetry").json()
    assert t["host"]["hostname"] and t["host"]["provider_mode"] == "stub"
    if not t["host"]["gb10_detected"]:  # this laptop
        assert t["gpu"] is None and t["system"] is None and t["unavailable_reason"] == telemetry.UNAVAILABLE
    assert t["inference"]["vision"]["latency"] is None and "STUB" in t["inference"]["vision"]["note"]
    assert t["inference_state"] == "STUB" and t["store"]["kind"] in ("sqlite", "mongo")
    assert "events" in t["log"] and isinstance(t["ingestion"]["counts"], dict)
    assert any("NOT TESTED" in n for n in t["notes"])
    assert c.get("/live.html").status_code == 200 and c.get("/live.js").status_code == 200


def test_video_frames():
    from backend.video import ffmpeg_exe

    exe = ffmpeg_exe()
    if not exe:
        print("SKIP video test: no ffmpeg (apt install ffmpeg or pip install imageio-ffmpeg)")
        return
    pipe.store.clear(INCIDENT)
    clip = Path(tempfile.mkdtemp(prefix="rescuebase-clip-")) / "flight.mp4"
    subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=3:size=64x48:rate=5",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    config.FRAME_INTERVAL_S, config.FRAME_MAX = 1.0, 12
    r = c.post("/api/ingest", files={"file": ("flight.mp4", clip.read_bytes(), "video/mp4")},
               data={"label": "REPLAY", "sector": "Sector 1", "captured_at": "2026-09-12T07:00:00"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["frames"] == 3 and len(j["events"]) == 3 and j["errors"] == []
    assert sorted(e["frame_offset_s"] for e in j["events"]) == [0, 1, 2]
    assert all(e["parent_source_id"] == j["source"]["source_id"] and e["label"] == "REPLAY" for e in j["events"])
    f2 = [e for e in j["events"] if e["frame_offset_s"] == 2][0]
    assert f2["captured_at"] == "2026-09-12T07:00:02" and f2["captured_at_source"] == "clip+offset"
    src = c.get(f"/api/sources/{j['source']['source_id']}").json()
    assert src["source_type"] == "video" and len(src["frames"]) == 3 and src["frame_interval_s"] == 1.0
    assert c.get(src["uri"]).status_code == 200 and c.get(f2["source_uri"]).status_code == 200


if __name__ == "__main__":
    test_extract_json()
    test_slice()
    test_worker()
    test_audio_paths()
    test_telemetry()
    test_video_frames()
    print("OK: stub tests passed (provider=stub, store=%s)" % pipe.store.kind)
