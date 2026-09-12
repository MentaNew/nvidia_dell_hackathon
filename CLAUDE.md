# RescueBase — notes for Claude Code

Read first: `docs/RESCUEBASE_SOURCE_OF_TRUTH.md` (canonical), then the engineering handoff `CLAUDE.md` on the
GBeast10 SSD (`D:\GB10_ARSENAL` on Windows; Linux mount path found via `lsblk`/`df -h`). Quickstart, layout, API
and demo run-book: `README.md`. Smoke check after any backend change: `python tests/test_smoke.py`.

Non-negotiables
- Never fabricate inference or imply it happened live. Stub providers label every event `stub (no inference performed)`.
- Humans decide: AI output is `AI_CANDIDATE` until a person confirms/rejects. No dispatch, no victim declarations, no medical priority.
- Provenance on every event: source file, timestamp, model_name, verification_state, evidence_refs. Keep the `simulated` flag visible.
- Offline-first: no CDNs, remote fonts, cloud APIs or hosted DBs. The UI is plain HTML/JS served by the backend.
- Minimum model set. Adapters in `backend/providers.py` speak OpenAI-compatible HTTP; swapping runtime/model is config only.

Conventions: config only via `RESCUEBASE_*` env vars (`backend/config.py`); store fallback Mongo → SQLite; ponytail
(lazy, stdlib-first) style; checkpoint with git after every working step.
