#!/usr/bin/env python3
"""GB10 acceptance: runs the six deployment paths against the RUNNING RescueBase server and writes a PASS / FAIL /
NOT RUN report with measured latency and memory. Stub providers are detected and never reported as inference.

  .venv/bin/python scripts/gb10_acceptance.py --image /path/site.jpg --audio /path/exercise_msg.wav --sector "Sector 4"
  .venv/bin/python scripts/gb10_acceptance.py --phase offline --audio /path/fresh_msg.wav      # after unplugging the uplink

Paths: 1 real vision + speech endpoints · 2 tests/test_real.py with the supplied image AND audio · 3 human check of
transcript/events against the sources · 4 running inbox worker on FRESH files · 5 OpenClaw draft update ·
6 offline: fresh message + sponsor action with the uplink disconnected.
Report: docs/ACCEPTANCE_<timestamp>.md (+ stdout). Stdlib only, plus Pillow / imageio-ffmpeg already in requirements.
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS: list[dict] = []
MEASURE: list[str] = []


# ---------------------------------------------------------------- helpers
def api(path: str, base: str, method: str = "GET", body: dict | None = None, timeout: int = 60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def post_file(base: str, path: str, fields: dict, filename: str, data: bytes, timeout: int = 900):
    b = "----rb" + uuid.uuid4().hex
    body = b"".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items())
    body += (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
             f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(base + path, data=body, method="POST", headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def record(step: str, status: str, detail: str = "", blocker: str = "") -> None:
    RESULTS.append({"step": step, "status": status, "detail": detail, "blocker": blocker})
    flag = {"PASS": "PASS    ", "FAIL": "FAIL    ", "NOT RUN": "NOT RUN "}[status]
    print(f"\n[{flag}] {step}\n         {detail}" + (f"\n         BLOCKER: {blocker}" if blocker else ""))


def nvidia_smi(query: str) -> str:
    if not shutil.which("nvidia-smi"):
        return ""
    try:
        return subprocess.run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def ram_used_mib() -> int | None:
    try:
        out = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=5).stdout.splitlines()
        return int(out[1].split()[2])
    except Exception:
        return None


class Sampler:
    """Peak GPU / system memory while a step runs (1 Hz)."""

    def __init__(self):
        self.stop = threading.Event()
        self.gpu_peak = self.ram_peak = None
        self.gpu_base, self.ram_base = self._gpu(), ram_used_mib()

    @staticmethod
    def _gpu():
        v = nvidia_smi("memory.used")
        return int(v.split("\n")[0]) if v and v.split("\n")[0].strip().isdigit() else None

    def __enter__(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self):
        while not self.stop.is_set():
            g, r = self._gpu(), ram_used_mib()
            self.gpu_peak = max(self.gpu_peak or 0, g) if g is not None else self.gpu_peak
            self.ram_peak = max(self.ram_peak or 0, r) if r is not None else self.ram_peak
            self.stop.wait(1)

    def __exit__(self, *a):
        self.stop.set()

    def text(self) -> str:
        g = f"GPU used base {self.gpu_base} MiB, peak {self.gpu_peak} MiB" if self.gpu_base is not None else "GPU memory: nvidia-smi n/a"
        r = f"RAM used base {self.ram_base} MiB, peak {self.ram_peak} MiB" if self.ram_base is not None else "RAM: free n/a"
        return f"{g}; {r}"


def fresh_variant(src: Path, tag: str) -> tuple[str, bytes]:
    """New bytes, same content: a text chunk in the image / a metadata comment in the audio container."""
    ext = src.suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"):
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo

        img = Image.open(src)
        img.load()
        info = PngInfo()
        info.add_text("Comment", f"rescuebase acceptance {tag}")
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG", pnginfo=info)
        return f"{src.stem}_{tag}.png", buf.getvalue()
    exe = shutil.which("ffmpeg")
    if not exe:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
    out = src.with_name(f"{src.stem}_{tag}{ext}")
    subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-c", "copy", "-metadata",
                    f"comment=rescuebase acceptance {tag}", str(out)], check=True, capture_output=True)
    data = out.read_bytes()
    out.unlink(missing_ok=True)
    return out.name, data


def wait_jobs(base: str, names: list[str], timeout: int = 900) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = api("/api/ingest/status", base)
        jobs = {j["name"]: j for j in st["recent"]}
        got = {n: jobs.get(n) for n in names}
        if all(j and j["status"] in ("completed", "failed") for j in got.values()):
            return got
        time.sleep(2)
    return {n: jobs.get(n) for n in names}  # whatever state they are in


def show_events(evs: list[dict]) -> None:
    for e in evs:
        cap = f"captured {e['captured_at']} ({e['captured_at_source']})" if e.get("captured_at") else "capture time unknown"
        loc = f"{e['location']['lat']},{e['location']['lon']}" if e.get("location") else "location unknown"
        print(f"    - [{e['event_id']}] {e['event_type']} conf {e['confidence']} | {cap} | {loc} | {e['label']} | model {e['model_name']}")
        print(f"      {e['observation']}")


def ask(prompt: str, no_prompt: bool) -> str | None:
    if no_prompt or not sys.stdin.isatty():
        return None
    a = input(f"{prompt} [y/n] ").strip().lower()
    return "PASS" if a.startswith("y") else "FAIL" if a.startswith("n") else None


# ---------------------------------------------------------------- phases
def preflight(base: str) -> dict | None:
    try:
        h = api("/api/health", base)
    except Exception as e:
        record("0 server", "FAIL", blocker=f"RescueBase not reachable at {base}: {e}")
        return None
    prov = h["providers"]
    gpu = nvidia_smi("name,driver_version,memory.total")
    MEASURE.append(f"hardware: {gpu or 'nvidia-smi n/a'}; python {sys.version.split()[0]}")
    for k in ("vision", "reasoning", "speech", "embedding"):
        MEASURE.append(f"{k}: endpoint {prov[k]['endpoint']} - {prov[k]['model']}")
    for name, url in (("vision", os.environ.get("RESCUEBASE_VLM_URL", "http://127.0.0.1:8001/v1")),
                      ("speech", os.environ.get("RESCUEBASE_STT_URL", "http://127.0.0.1:8003/v1"))):
        try:
            v = api("/version", url.rsplit("/v1", 1)[0], timeout=5)
            MEASURE.append(f"{name} server version: {v}")
        except Exception:
            pass
    stub = h["inference"] == "STUB"
    v_ok, s_ok = prov["vision"]["endpoint"] == "READY", prov["speech"]["endpoint"] == "READY"
    if stub:
        record("1 real vision + speech endpoints", "NOT RUN", f"store {h['store']} {h['store_status']}, network {h['network']}",
               blocker="server runs STUB providers (RESCUEBASE_PROVIDER=stub): nothing below is an inference result")
    elif v_ok and s_ok:
        record("1 real vision + speech endpoints", "PASS", f"vision {prov['vision']['model']} READY; speech {prov['speech']['model']} READY; "
               f"store {h['store']} {h['store_status']}; inference state {h['inference']}")
    else:
        record("1 real vision + speech endpoints", "FAIL", f"vision {prov['vision']['endpoint']}, speech {prov['speech']['endpoint']}",
               blocker="start scripts/serve_models.sh vlm / stt and check RESCUEBASE_*_URL")
    h["_stub"], h["_endpoints_ok"] = stub, v_ok and s_ok
    return h


def step_test_real(image: Path, audio: Path, h: dict, no_prompt: bool) -> None:
    step = "2 tests/test_real.py with supplied image AND audio"
    if h["_stub"] or not h["_endpoints_ok"]:
        record(step, "NOT RUN", blocker="stub providers" if h["_stub"] else "endpoints not READY (see step 1)")
        return record("3 transcript/events checked against sources", "NOT RUN", blocker="depends on step 2")
    env = {**os.environ, "RESCUEBASE_PROVIDER": "openai", "RESCUEBASE_TEST_IMAGE": str(image), "RESCUEBASE_TEST_AUDIO": str(audio)}
    t0 = time.time()
    with Sampler() as smp:
        p = subprocess.run([sys.executable, str(ROOT / "tests" / "test_real.py")], env=env, capture_output=True, text=True, cwd=ROOT)
    out = p.stdout + p.stderr
    print(out[-3000:])
    MEASURE.append(f"test_real.py wall {time.time() - t0:.1f}s; {smp.text()}")
    for line in out.splitlines():
        if line.startswith(" - "):
            MEASURE.append("test_real: " + line[3:])
    if p.returncode != 0:
        return record(step, "FAIL", blocker=out.strip().splitlines()[-1][:300] if out.strip() else f"exit {p.returncode}")
    record(step, "PASS", f"exit 0 in {time.time() - t0:.1f}s; {smp.text()}")
    # 3: human check against the sources
    v = ask(f"Do the image events above describe what is actually in {image.name}?", no_prompt)
    a = ask(f"Does the transcript above match what is said in {audio.name} (identifiers, negations)?", no_prompt)
    if v is None or a is None:
        record("3 transcript/events checked against sources", "NOT RUN", blocker="needs a person: rerun without --no-prompt, or judge from the printout")
    else:
        record("3 transcript/events checked against sources", "PASS" if v == a == "PASS" else "FAIL", f"image {v}, transcript {a}")


def step_worker(base: str, image: Path | None, audio: Path | None, sector: str, h: dict, step: str = "4 running inbox worker on fresh files") -> list[dict]:
    st = api("/api/ingest/status", base)
    if not st.get("enabled") or not st.get("running"):
        record(step, "FAIL", blocker="inbox worker not running in the server (RESCUEBASE_INBOX_ENABLED=1 and restart)")
        return []
    tag = datetime.now().strftime("%H%M%S")
    dropped, t0 = [], time.time()
    for src in (image, audio):
        if src:
            name, data = fresh_variant(src, tag)
            r = post_file(base, "/api/inbox/drop", {"label": "EXERCISE", "sector": sector, "note": f"acceptance {tag}"}, name, data)
            dropped.append(Path(r["path"]).name)
    with Sampler() as smp:
        jobs = wait_jobs(base, dropped)
    wall = time.time() - t0
    events, lines, ok = [], [], True
    for n, j in jobs.items():
        if not j or j["status"] != "completed":
            ok = False
            lines.append(f"{n}: {j['status'] if j else 'never seen'} {j.get('error', '') if j else ''}")
            continue
        evs = [api(f"/api/events/{i}", base) for i in j["event_ids"]]
        events += evs
        real = evs and not evs[0]["model_name"].startswith("stub")
        ok &= bool(real)
        lines.append(f"{n}: {len(evs)} event(s), processing {j['duration_s']}s, model {evs[0]['model_name'] if evs else 'n/a'}")
        show_events(evs)
        if j.get("source_id"):
            try:
                print("      transcript:", api(f"/api/transcripts/{j['source_id']}", base)["text"][:400])
            except Exception:
                pass
    t2e = api("/api/ingest/status", base).get("time_to_entry_s")
    MEASURE.append(f"{step}: wall {wall:.1f}s for {len(dropped)} file(s); drop->entry {t2e}; {smp.text()}")
    if h["_stub"]:
        record(step, "NOT RUN", "mechanics ran with STUB providers: " + "; ".join(lines), blocker="stub providers, not an inference result")
    else:
        record(step, "PASS" if ok and dropped else "FAIL", "; ".join(lines) + f"; wall {wall:.1f}s; {smp.text()}",
               blocker="" if ok else "see job errors above")
    return events


def step_openclaw(base: str, step: str = "5 OpenClaw draft update (source-linked)") -> None:
    if not shutil.which("openclaw"):
        return record(step, "NOT RUN", blocker="`openclaw` not on PATH: follow integrations/openclaw/README.md (needs internet once)")
    before = {u["update_id"] for u in api("/api/updates?limit=50", base)}
    t0 = time.time()
    with Sampler() as smp:
        p = subprocess.run(["bash", str(ROOT / "integrations" / "openclaw" / "run_update.sh")], capture_output=True, text=True, timeout=900, cwd=ROOT)
    out = (p.stdout + p.stderr)[-2000:]
    print(out)
    new = [u for u in api("/api/updates?limit=50", base) if u["update_id"] not in before]
    MEASURE.append(f"{step}: wall {time.time() - t0:.1f}s; {smp.text()}")
    if not new:
        return record(step, "FAIL", f"exit {p.returncode}, no new update posted in {time.time() - t0:.0f}s", blocker=out.strip().splitlines()[-1][:300] if out.strip() else "no output")
    u = new[0]
    print(f"    update {u['update_id']} by {u['agent']} using {u['model_name']}: cites {u['cited_event_ids']}\n    {u['text'][:600]}")
    record(step, "PASS" if u["cited_event_ids"] else "FAIL", f"{u['update_id']} agent {u['agent']} model {u['model_name']} cites {len(u['cited_event_ids'])} event(s) in {time.time() - t0:.0f}s",
           blocker="" if u["cited_event_ids"] else "update cites no known event")


def step_offline(base: str, audio: Path | None, image: Path | None, sector: str, h: dict, no_prompt: bool) -> None:
    net = api("/api/health", base)["network"]
    if net != "OFFLINE" and not no_prompt and sys.stdin.isatty():
        input("Disconnect the EXTERNAL uplink now (keep the LAN / local screen). Press Enter when done… ")
    t0 = time.time()
    while api("/api/health", base)["network"] != "OFFLINE" and time.time() - t0 < 120:
        time.sleep(2)
    hh = api("/api/health", base)
    if hh["network"] != "OFFLINE":
        return record("6 offline: fresh message + sponsor action", "FAIL", blocker="probe still reports ONLINE after 120s: uplink not actually cut (or RESCUEBASE_NET_PROBE reachable via LAN)")
    print(f"    network OFFLINE confirmed after {time.time() - t0:.0f}s; inference state {hh['inference']}, store {hh['store_status']}")
    events = step_worker(base, image, audio, sector, h, step="6a offline: fresh message through the worker")
    step_openclaw(base, step="6b offline: sponsor action again")
    ok = all(r["status"] == "PASS" for r in RESULTS if r["step"].startswith("6"))
    record("6 offline: fresh message + sponsor action", "PASS" if ok else ("NOT RUN" if h["_stub"] else "FAIL"),
           f"{len(events)} new event(s) while OFFLINE; see 6a/6b", blocker="" if ok else "see 6a/6b")


def write_report(phase: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    p = ROOT / "docs" / f"ACCEPTANCE_{ts}.md"
    lines = [f"# GB10 acceptance ({phase}) — {datetime.now().isoformat(timespec='seconds')}", "",
             "| step | result | detail | blocker |", "|---|---|---|---|"]
    lines += [f"| {r['step']} | **{r['status']}** | {r['detail'].replace('|', '/')} | {r['blocker'].replace('|', '/')} |" for r in RESULTS]
    lines += ["", "## Measurements", ""] + [f"- {m}" for m in MEASURE]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines[2:]))
    print(f"\nreport: {p}")
    return p


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=os.environ.get("RESCUEBASE_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--image", type=Path)
    ap.add_argument("--audio", type=Path)
    ap.add_argument("--sector", default="Sector 4")
    ap.add_argument("--phase", choices=["online", "offline", "all"], default="online")
    ap.add_argument("--no-prompt", action="store_true", help="never wait for a person (human checks become NOT RUN)")
    a = ap.parse_args()
    for p in (a.image, a.audio):
        if p and not p.exists():
            sys.exit(f"missing file: {p}")
    h = preflight(a.base)
    if h is None:
        write_report(a.phase)
        sys.exit(1)
    if a.phase in ("online", "all"):
        if a.image and a.audio:
            step_test_real(a.image, a.audio, h, a.no_prompt)
        else:
            record("2 tests/test_real.py with supplied image AND audio", "NOT RUN", blocker="pass both --image and --audio")
            record("3 transcript/events checked against sources", "NOT RUN", blocker="depends on step 2")
        step_worker(a.base, a.image, a.audio, a.sector, h)
        step_openclaw(a.base)
    if a.phase in ("offline", "all"):
        step_offline(a.base, a.audio, a.image, a.sector, h, a.no_prompt)
    else:
        record("6 offline: fresh message + sponsor action", "NOT RUN", blocker="run again with --phase offline after disconnecting the uplink")
    write_report(a.phase)
    sys.exit(0 if all(r["status"] == "PASS" for r in RESULTS) else 1)


if __name__ == "__main__":
    main()
