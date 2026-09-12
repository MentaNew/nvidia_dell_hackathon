# RescueBase

Always-on, local incident log for infrastructure site operations (hydropower site during a disruption is the worked
example). Drone imagery and crew radio audio arrive in a local inbox; the GB10 analyses and transcribes them locally;
every result becomes a structured, source-linked **draft** event on a shared timeline; people confirm or reject.
When the external internet goes away, nothing changes.

```
DRONE IMAGERY + RADIO AUDIO  →  LOCAL ANALYSIS / TRANSCRIPTION  →  SOURCE-LINKED DRAFT EVENTS  →  SHARED TIMELINE  →  HUMAN REVIEW
```

Product doc: [docs/RESCUEBASE_SOURCE_OF_TRUTH.md](docs/RESCUEBASE_SOURCE_OF_TRUTH.md) · decision log:
[docs/STATUS_LOG.md](docs/STATUS_LOG.md) · submission notes: [docs/SUBMISSION_NOTES.md](docs/SUBMISSION_NOTES.md) ·
sponsor component: [integrations/openclaw/README.md](integrations/openclaw/README.md).

## Run

```bash
scripts/run.sh                       # API + UI + inbox worker on http://localhost:8000 (creates .venv, installs requirements)
python tests/test_smoke.py           # stub providers + SQLite: slice, worker, video, provenance rules (no GPU)
RESCUEBASE_PROVIDER=openai python tests/test_real.py   # real endpoints: prints the measurement block (GB10)
docker compose up -d                 # optional MongoDB; without it the app uses SQLite (the tested path)
```

All config is `RESCUEBASE_*` env vars ([.env.example](.env.example)). `RESCUEBASE_PROVIDER=stub` runs without any
model: every stub event is labelled `stub (no inference performed)` and the header says `LOCAL INFERENCE: STUB`.

## GB10: from zero to real inference

1. `lsblk; df -h` → find the GBeast10 SSD → `export RESCUEBASE_MODEL_ROOT=/mnt/<ssd>/GB10_ARSENAL/models`.
2. `scripts/serve_models.sh vlm` → Qwen3-VL on :8001 (vLLM, OpenAI-compatible). With only this server the whole
   image path and the query path work (reasoning defaults to the VLM). Then `stt` → Whisper Large v3 Turbo on :8003
   for the audio path. `llm` (Nemotron) and `embed` are optional; keyword retrieval is the default.
   Flags follow the model cards; validate on first launch. Memory fractions are configuration, not proof of fit:
   watch `nvidia-smi` while both servers load.
3. `cp .env.example .env && scripts/run.sh` → header must read `LOCAL INFERENCE: ENDPOINT UP · no successful run yet`.
4. `RESCUEBASE_PROVIDER=openai python tests/test_real.py` → first real image through the model; header flips to
   `LOCAL INFERENCE: OK · last run hh:mm:ss`. Paste the printed MEASUREMENTS block into `docs/STATUS_LOG.md`.
5. Drop Cezary's assets into `data/inbox/replay/` (recorded footage), `data/inbox/exercise/` (scripted radio),
   `data/inbox/satellite/`; log rights in [data/demo/ASSETS.md](data/demo/ASSETS.md).
6. Sponsor component: follow [integrations/openclaw/README.md](integrations/openclaw/README.md).

Any OpenAI-compatible server works (vLLM, NIM, llama.cpp, Ollama): point `RESCUEBASE_*_URL` / `*_MODEL` at it.

## Always-on ingestion

`data/inbox/` is watched every 2 s (`backend/worker.py`, threads inside the API process; no browser needed).

- **Settle:** a file is read only after its size/mtime stop changing for `RESCUEBASE_INBOX_SETTLE_S` (2 s), so
  partially written files are never processed.
- **Identity:** SHA-256 of the content, persisted as a job in the store. Restarts never re-ingest completed inputs.
  Same bytes under a new name → recorded as `duplicate_paths` on the original job, not a new source (duplicate
  evidence is not corroboration). Different files with similar content stay separate sources.
- **States:** queued → processing → completed | retrying | failed. Bounded retries (`RESCUEBASE_INGEST_RETRIES`, 2),
  exponential backoff, then FAILED. A failed input never blocks the next one. Bounded queue, one model call at a
  time by default (`RESCUEBASE_INFER_CONCURRENCY`).
- **Labels:** subfolder name sets the provenance label (`exercise/`, `replay/`, `satellite/`, `archival/`, `live/`);
  an optional sidecar `<file>.json` sets `sector`, `label`, `note`, `captured_at`, `location {lat, lon}`.
- **Measured:** `GET /api/ingest/status` reports drop→entry seconds (file mtime → saved event) per completed job,
  with median and max. That is the "time to a usable incident entry" figure: same exercise inputs, small sample,
  method stated here.
- **Delivering inputs:** copy files into the folder (USB, scp, a synced share), or `POST /api/inbox/drop`
  (multipart `file`, `label`, `sector`), which the UI's **● Record exercise radio message** button uses: it records
  from the browser microphone and drops the recording into `inbox/exercise/`. Browser and phone formats
  (webm/ogg/m4a) are transcoded to 16 kHz WAV before Whisper; the original recording stays the evidence.
  Microphone capture needs a secure context: use the UI on `localhost` (the GB10's own browser) or drop files.

## Recorded replay (video)

A clip dropped in the inbox is kept as a `video` source; one frame every `RESCUEBASE_FRAME_INTERVAL_S` (10 s, max
`RESCUEBASE_FRAME_MAX`) goes through the image path. Each frame event keeps `parent_source_id` and `frame_offset_s`;
the evidence panel shows the frame and the clip seeked to that offset under the label "RECORDED REPLAY · playback is
real time · inference sampled 1 frame every N s". No claim of continuous real-time video understanding.
ffmpeg comes from the `imageio-ffmpeg` wheel (aarch64 supported) or the system `ffmpeg`.

## What every event exposes

`observation` (what was seen or reported, negations preserved) · `source_type` + `source_uri` (evidence link) ·
`captured_at` + `captured_at_source` (EXIF / sidecar / clip+offset / operator) or "capture time unknown" ·
`ingested_at` (always, UTC) · `time_basis` (which one orders the timeline) · `location` (EXIF or sidecar only, else
unknown and unpinned) · `sector` · `model_name` · `confidence` (model-stated, uncalibrated) · `verification_state`
(`AI_CANDIDATE` until a person confirms/rejects) · `label` (`LIVE` / `REPLAY` / `ARCHIVAL` / `EXERCISE` / `SATELLITE`) ·
`related_event_ids` (same source) · `job_id`.

Rules enforced in prompts and code: no victim/casualty claims, no dispatch or medical priority, no "safe" or
"passable" judgements, no model-guessed coordinates, visual observations and spoken reports stay separate events,
agreement between them is not confirmation, conflicting reports are both kept.

## Live GB10 page

`http://localhost:8000/live.html` (blue **LIVE GB10 →** button in the header; **← Back to incident log** on the page).
Three scrolling graphs update every second from a server-side 1 Hz ring buffer (`GET /api/telemetry/history`,
3 min kept, so 60 s of history survives page navigation): GPU utilization on a fixed 0–100 % scale with ▲ job
start / ▼ job end markers (V vision, T transcription, R report) and shaded model-call spans; unified memory used on
a fixed 0–100 % scale; latency, where ● per-call model latency and ◆ queue→event (file drop → saved event) are plotted
as separate series because they measure different things. Tiles (`GET /api/telemetry`, every 2 s) show GPU, one
unified-memory figure (the GB10 has a single pool: nvidia-smi if it reports it, else procfs, never RAM + VRAM),
load, per-provider p50/p95, ingestion throughput, log counts, network, store, and the detection evidence.

Hardware readings appear only when the server detects an NVIDIA GB10 (`nvidia-smi` GPU name contains "GB10").
If automatic detection fails on the box, `RESCUEBASE_ASSUME_GB10=1` unlocks the real nvidia-smi/procfs readings;
it never invents values. Anything a tool reports as N/A, and everything on a non-GB10 host, reads
"Unavailable — awaiting GB10 telemetry" (graphs leave gaps, never zeros). Stub providers produce no latency.
No CDN, no libraries: plain canvas. **Hardware telemetry is UNVERIFIED on a GB10** until the acceptance run; only
the parsers, the unavailable path and the graphs were tested on a laptop.

## Four states in the header

`EXTERNAL INTERNET` (a real HTTP response from an external URL) · `LOCAL INFERENCE` (endpoint reachable **and**
whether a real run succeeded in this process: `ENDPOINT UP · no successful run yet` vs `OK · last run hh:mm:ss`) ·
`LOCAL LOG` (SQLite/Mongo health) · `INGESTION` (worker watching, queued/processing counts).

## API

`GET /api/health` · `GET /api/ingest/status` · `POST /api/ingest` (multipart: file, sector, label, simulated,
captured_at, note) · `GET /api/events?state=&sector=&source_id=&since=&until=` · `GET /api/events/{id}` ·
`POST /api/events/{id}/verify {state, notes}` · `GET /api/sources` · `GET /api/sources/{id}` ·
`GET /api/transcripts/{source_id}` · `POST /api/query {question}` · `POST /api/sitrep` · `GET/POST /api/updates` ·
`POST /api/updates/{id}/verify` · `GET /api/map` · `POST /api/demo/reset`.

## Layout

```
backend/config.py     RESCUEBASE_* env → settings (.env supported)
backend/models.py     Event / Observation schemas, enums (labels, verification, confidence)
backend/providers.py  Vision / Reasoning / Speech / Embedding adapters over OpenAI-compatible HTTP, labelled stubs,
                      prompts, per-provider last-success tracking, network probe
backend/store.py      incident log: Mongo (preferred) → SQLite fallback, same calls
backend/pipeline.py   ingest (image/audio/text/video → events), list/verify, query, SITREP, updates, health, demo reset
backend/worker.py     always-on inbox worker (settle, hash identity, bounded queue/retries, status, drop→entry timing)
backend/video.py      frame sampling from recorded clips (ffmpeg)
backend/app.py        FastAPI routes + static UI + /data media
frontend/             plain HTML/CSS/JS (no build, no CDN): status header, ingestion panel, updates, evidence, cards, timeline, query
integrations/openclaw OpenClaw config, skill, client script, runbook (sponsor component)
scripts/              run.sh, serve_models.sh (vLLM launch on the GB10)
tests/                test_smoke.py (stubs), test_real.py (real endpoints, prints measurements)
```

## The decisive offline demonstration

1. `scripts/run.sh` (worker starts with it); header shows the four states.
2. Copy a recorded drone clip or frame into `data/inbox/replay/` → frame events appear by themselves.
3. Copy an exercise radio recording into `data/inbox/exercise/` → transcript + REPORTED_EVENT cards appear.
4. Click a card: evidence image / clip at offset / audio with transcript; Confirm or Reject.
5. Ask the log: "What has been reported in Sector 4?", "What remains unverified?", "Which source supports ev_…?"
6. Disconnect the dedicated external uplink only (keep the LAN between laptop and GB10, or present from the GB10
   itself). Within ~5 s the banner reads `EXTERNAL INTERNET: OFFLINE · LOCAL INFERENCE: OK · LOCAL LOG: READY`.
7. Record a fresh exercise message with an identifier chosen by the audience; drop it in `data/inbox/exercise/`.
8. Watch the job go queued → processing → completed and the new event appear with that identifier in its
   transcript. `LOCAL INFERENCE` shows the new last-run time. No cache, no canned result.

## Known limitations

Tested with stubs on a laptop; real-model and GB10 runs are pending (see STATUS_LOG). Model launch flags and memory
coexistence are unverified until first launch. Audio needs the Whisper endpoint; the VLM alone does not transcribe.
Confidence labels are uncalibrated. Frame offsets are approximate (±half an interval). No authentication on the
local API (single command post on a private network). MongoDB path is code-complete but untested; SQLite is the
tested store.
