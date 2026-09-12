# RescueBase

Local multimodal incident-intelligence appliance for disaster-response command posts.
*When the network goes down, the intelligence layer shouldn't disappear with it.*

Canonical product doc: [docs/RESCUEBASE_SOURCE_OF_TRUTH.md](docs/RESCUEBASE_SOURCE_OF_TRUTH.md).

## Run

```bash
scripts/run.sh                 # API + UI on http://localhost:8000  (creates .venv, installs requirements.txt)
docker compose up -d           # optional: MongoDB incident memory; without it the app falls back to SQLite
python tests/test_smoke.py     # end-to-end slice with stub providers + SQLite, no GPU needed
```

Config is all `RESCUEBASE_*` env vars; copy [.env.example](.env.example) to `.env`.
No GPU (laptop UI work): `RESCUEBASE_PROVIDER=stub`. Every stub event is labelled
`stub (no inference performed)` and the header shows `LOCAL AI: STUB`. Nothing is ever fabricated as live inference.

## GB10 day, hour 0-2

1. `lsblk; df -h` → find the GBeast10 SSD → `export RESCUEBASE_MODEL_ROOT=/mnt/<ssd>/GB10_ARSENAL/models`
2. `scripts/serve_models.sh vlm` → Qwen3-VL on :8001. With only this server up the whole slice works
   (reasoning defaults to the VLM). Add `llm` (Nemotron :8002, then set `RESCUEBASE_LLM_URL/MODEL`), `stt` (:8003), `embed` (:8004).
3. `docker compose up -d && scripts/run.sh` → open http://localhost:8000 → header must read `LOCAL AI: OPERATIONAL`.
4. Drop demo assets into `data/demo/` (log every asset in [data/demo/ASSETS.md](data/demo/ASSETS.md); optional
   `manifest.json`, see `manifest.example.json`), press **Demo reset**: everything is re-ingested through the live pipeline.

Any OpenAI-compatible server works (vLLM, NIM, llama.cpp, Ollama): point the `*_URL` / `*_MODEL` vars at it.

## What exists

```
backend/config.py     RESCUEBASE_* env → settings (.env supported)
backend/models.py     Event schema, enums, Observation schema handed to the models (constrained JSON)
backend/providers.py  Vision / Reasoning / Speech / Embedding adapters over OpenAI-compatible HTTP + labelled stubs;
                      prompts; network probe
backend/store.py      incident memory: Mongo (preferred) → SQLite fallback, same 5 calls
backend/pipeline.py   ingest (image/audio/text → events, EXIF time+GPS provenance), list/verify,
                      query (deterministic retrieval → cited synthesis), SITREP, health, demo reset
backend/app.py        FastAPI routes + static UI + /data media
frontend/             plain HTML/CSS/JS command UI (no build step, no CDN, works offline)
scripts/              run.sh, serve_models.sh (vLLM launch on the GB10)
data/demo/            demo assets + license log; data/uploads/ ingested media; data/map.png optional static map
```

API: `GET /api/health` · `POST /api/ingest` (multipart: file, sector, simulated, note) · `GET /api/events?state=&sector=&source_id=&since=&until=`
· `POST /api/events/{id}/verify {state, notes}` · `POST /api/query {question}` · `POST /api/sitrep` · `GET /api/sources`
· `GET /api/transcripts/{source_id}` · `GET /api/map` · `POST /api/demo/reset`

Event object: `event_id, incident_id, timestamp, source_type, source_id, source_name, source_uri, sector, location, region_hint,
event_type, observation, confidence (LOW/MEDIUM/HIGH/UNKNOWN), verification_state (UNVERIFIED/AI_CANDIDATE/HUMAN_CONFIRMED/HUMAN_REJECTED/UNKNOWN),
model_name, simulated, related_event_ids, evidence_refs, human_notes, created_at`.

## Demo run-book

1. Header: `LOCAL AI: OPERATIONAL · EXTERNAL NETWORK: ONLINE · MEMORY: MONGO READY`.
2. Ingest a real aerial image (sector set) → candidate event cards appear, click one → source image in the evidence panel.
3. Ingest a *SIMULATED* responder-radio clip (checkbox on) → transcript + REPORTED_EVENT cards on the timeline.
4. Confirm / reject a few cards (human authority).
5. Query: "What changed in Sector 4?" / "What remains unverified?" → answer cites `[ev_…]`, each link opens the evidence.
6. Pull the network. Within ~5 s the red banner reads `EXTERNAL NETWORK: OFFLINE · LOCAL RESCUEBASE: OPERATIONAL`.
7. Query again, ingest another local asset, press **Low-bandwidth SITREP** (shows bytes to transmit vs MB of source media).

Failure plan: any model server down → header shows DEGRADED/UNAVAILABLE and the affected ingest fails loudly
(never silently faked); embeddings down → keyword retrieval; Mongo down → SQLite; map missing → sector list only.
