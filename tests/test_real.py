"""Real-inference check against the configured local endpoints (run on the GB10, never with stubs).

    RESCUEBASE_PROVIDER=openai python tests/test_real.py
    RESCUEBASE_TEST_IMAGE=/path/site.jpg RESCUEBASE_TEST_AUDIO=/path/radio.wav python tests/test_real.py

Prints a measurement block (hardware, models, latency) to paste into docs/STATUS_LOG.md. Nothing here is cached
or canned: if an endpoint is down the test fails loudly.
"""
import io
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("RESCUEBASE_PROVIDER", "openai")
os.environ["RESCUEBASE_INCIDENT"] = os.environ.get("RESCUEBASE_TEST_INCIDENT", "real-test")
os.environ["RESCUEBASE_INBOX_ENABLED"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from backend import config  # noqa: E402
from backend.app import app, pipe  # noqa: E402

assert config.PROVIDER != "stub", "test_real.py needs real providers (RESCUEBASE_PROVIDER=openai)"
c = TestClient(app)


def synthetic_site() -> bytes:
    """A drawn scene (labelled as such) so the plumbing can be exercised before real assets arrive."""
    img = Image.new("RGB", (960, 640), (118, 128, 96))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 420, 960, 640], fill=(70, 110, 160))  # water
    d.rectangle([60, 300, 900, 360], fill=(80, 80, 80))  # road / crest
    d.polygon([(500, 300), (700, 120), (860, 300)], fill=(150, 110, 70))  # slope
    d.rectangle([120, 200, 260, 300], fill=(190, 190, 190))  # building
    d.text((16, 16), "SYNTHETIC TEST SCENE - drawn shapes, not a photograph", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def gpu_line() -> str:
    if shutil.which("nvidia-smi"):
        try:
            return subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader"],
                                  capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            pass
    return "nvidia-smi unavailable"


def main() -> None:
    pipe.store.clear(config.INCIDENT_ID)
    h = c.get("/api/health").json()
    print("health:", {k: v["endpoint"] for k, v in h["providers"].items()}, "| inference:", h["inference"])
    assert h["providers"]["vision"]["endpoint"] == "READY", f"vision endpoint not reachable at {config.VLM_URL}"
    measurements = [f"hardware: {gpu_line()}", f"vision: {pipe.vision.name}", f"reasoning: {pipe.reasoning.name}"]

    image = Path(os.environ["RESCUEBASE_TEST_IMAGE"]).read_bytes() if os.environ.get("RESCUEBASE_TEST_IMAGE") else synthetic_site()
    name = Path(os.environ.get("RESCUEBASE_TEST_IMAGE", "synthetic_site.jpg")).name
    t0 = time.time()
    r = c.post("/api/ingest", files={"file": (name, image, "image/jpeg")}, data={"sector": "Sector 1", "label": "EXERCISE"})
    dt = time.time() - t0
    assert r.status_code == 200, r.text
    evs = r.json()["events"]
    assert evs and not evs[0]["model_name"].startswith("stub"), "image path did not run a real model"
    measurements.append(f"image -> {len(evs)} event(s) in {dt:.1f}s ({len(image) // 1024} KB)")
    for e in evs:
        print(f"  {e['event_type']:<24} conf {e['confidence']:<7} {e['observation']}")
    assert c.get("/api/health").json()["inference"] == "PROVEN"

    if os.environ.get("RESCUEBASE_TEST_AUDIO"):
        p = Path(os.environ["RESCUEBASE_TEST_AUDIO"])
        t0 = time.time()
        r = c.post("/api/ingest", files={"file": (p.name, p.read_bytes(), "audio/wav")}, data={"sector": "Sector 1", "label": "EXERCISE"})
        dt = time.time() - t0
        assert r.status_code == 200, r.text
        assert r.json()["transcript"].strip(), "empty transcript"
        measurements.append(f"audio -> transcript {len(r.json()['transcript'])} chars, {len(r.json()['events'])} event(s) in {dt:.1f}s")
        print("  transcript:", r.json()["transcript"][:200])
        for e in r.json()["events"]:
            print(f"  {e['event_type']:<24} conf {e['confidence']:<7} {e['observation']}")
    else:
        measurements.append("audio: skipped (set RESCUEBASE_TEST_AUDIO=/path/radio.wav)")

    t0 = time.time()
    q = c.post("/api/query", json={"question": "What has been reported in Sector 1 and what remains unverified?"}).json()
    measurements.append(f"query -> {len(q['cited'])} cited of {len(q['events'])} retrieved in {time.time() - t0:.1f}s")
    print("  answer:", q["answer"][:300])
    assert q["answer"].strip() and not q["uncited_claims"], f"answer cites unknown ids: {q['uncited_claims']}"

    print("\nMEASUREMENTS (" + time.strftime("%Y-%m-%d %H:%M:%S") + ")")
    for m in measurements:
        print(" -", m)
    print("OK: real-inference test passed")


if __name__ == "__main__":
    main()
