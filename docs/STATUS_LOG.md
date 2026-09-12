# RescueBase status and decision log

Format: TIME (EDT) / DECISION / WHY / EVIDENCE / STATUS. Status vocabulary: implemented · tested with stubs ·
tested with real models · tested on GB10 · pending · blocked.

| TIME | DECISION | WHY | EVIDENCE | STATUS |
|---|---|---|---|---|
| 09-12 04:05 | Bootstrap: FastAPI + OpenAI-compatible adapters + Mongo→SQLite store + plain HTML/JS UI | Handoff asked for a vertical slice by hour 4; one process, no build step, works offline | `python tests/test_smoke.py` passes; UI rendered in browser | tested with stubs |
| 09-12 08:12 | Network probe = real HTTP status, not TCP connect | On this laptop a TCP connect to an unroutable host "succeeds" (VPN/sandbox completes handshakes), so an unplugged cable would read ONLINE | Probe check: default URL ONLINE 0.7 s; unroutable OFFLINE 2.0 s; bad DNS OFFLINE 0.7 s | tested (laptop) |
| 09-12 13:25 | Plan against the 18:30 cutoff; feature freeze 17:00 | Earlier of the two published deadlines | Brief (dashboard 22:00 vs schedule 18:30) | decided |
| 09-12 13:31 | Merge GitHub "first commit" into local history and push (no force) | Preserve both histories | `d29f82e` on origin/main | done |
| 09-12 13:40 | Always-on inbox worker (settle, SHA-256 identity persisted in store, bounded queue/retries, status API) | P0: manual upload alone is not always-on | `test_worker`: 4 inputs → 3 completed + 1 failed, duplicate recorded not re-ingested, partial file skipped, restart re-ingests nothing, replaced bad file succeeds, retry bounded (attempts 2/2 → failed) | tested with stubs |
| 09-12 13:40 | Capture time vs ingestion time kept separate; labels LIVE/REPLAY/ARCHIVAL/EXERCISE/SATELLITE; location only from EXIF/sidecar | Brief §7: never disguise ingest time as capture time; no model-guessed coordinates | `test_slice`/`test_worker` assert `time_basis`, `captured_at_source`, unknown location stays null | tested with stubs |
| 09-12 13:40 | Video = recorded replay: frames every N s via ffmpeg (imageio-ffmpeg wheel, aarch64 ok) | P1; no claim of continuous video understanding | `test_video_frames`: 3 s clip → 3 frame events at 0/1/2 s with `clip+offset` capture times | tested with stubs |
| 09-12 13:45 | `LOCAL INFERENCE` distinguishes endpoint-up from a real successful run (per-provider last success/error) | Brief §8: "AI operational" must not mean "server lists models" | health `inference` ∈ STUB / UNAVAILABLE / ENDPOINT_UP_UNPROVEN / PROVEN / DEGRADED; `test_real.py` asserts PROVEN after one image | tested with stubs; real pending |
| 09-12 13:55 | Sponsor component = OpenClaw (standalone) with local vLLM provider (`models.mode: replace`), skill `rescuebase-log` posting source-linked draft updates to `POST /api/updates`; NemoClaw/OpenShell as stretch | Smallest documented path with real work and structurally no cloud model; NemoClaw's interactive quickstart defaults to NVIDIA cloud endpoints and its sandbox cannot reach 127.0.0.1 | Research report (official docs, 12 Sep); API side: `test_slice` update assertions pass | implemented; **not executed** (needs GB10 + OpenClaw) |
| 09-12 13:55 | Drop→entry timing collected per job (file mtime → saved event) as the business-value measurement | Brief §10: measure time to a usable entry with the same exercise inputs, method stated | `GET /api/ingest/status.time_to_entry_s` (median/max, n) | implemented; numbers pending on GB10 |
| 09-12 13:50 | Live run of the always-on path on the laptop (stub providers): 3 inbox inputs (clip + image + text with sidecars, plus a byte-identical copy) processed with no browser action | Prove the worker inside the API process, not just in tests | 3 jobs completed, 5 events (3 frame events at clip+offset capture times 09:15:00/10/20, text report with sidecar sector/time), skill client listed 5 candidates and posted update `upd_d426b75f24`; drop→entry median 9 s (includes server start + 2 s settle) | tested with stubs (live process) |
| 09-12 13:52 | Job records are merged, not replaced | Live run lost the duplicate-file record to a scanner/worker write race (dedupe itself held: 5 events, not 6) | `_patch()` in worker.py; tests pass | fixed, tested with stubs |
| 09-12 13:55 | Browser "Record exercise radio message" → `POST /api/inbox/drop` → inbox worker; audio transcoded to 16 kHz WAV before Whisper | Demo step 7 needs a fresh onstage message without file juggling; phone/browser formats must reach Whisper | `test_audio_paths` (wav direct, webm→wav) | tested with stubs |
| 09-12 13:58 | Live restart + drop check on the laptop | Prove restart safety and the record→inbox path in a running process | After restart: 0 re-ingested, 5 events unchanged, duplicate copy now listed on its job; `POST /api/inbox/drop` of a 19 KB webm → transcoded to WAV → event in 5 s with EXERCISE label and sidecar sector | tested with stubs (live process) |
| — | Real image through Qwen3-VL on GB10 | P0 | run `tests/test_real.py`, paste MEASUREMENTS here | pending |
| — | Real audio through Whisper on GB10 | P0 | `RESCUEBASE_TEST_AUDIO=… tests/test_real.py` | pending |
| — | Image + audio concurrently; memory use with both servers loaded | Brief §10 | `nvidia-smi` while both run | pending |
| — | OpenClaw smoke run + one posted update | P0 sponsor evidence | `integrations/openclaw/run_update.sh`, `data/logs/openclaw.log`, `/api/updates` | pending |
| — | ASTRA_HANDOFF.md | D: not mounted on the laptop; never read | — | blocked (get the file from the SSD) |

## Measurements (paste from `tests/test_real.py` and `nvidia-smi`)

_(none yet — laptop has no GPU; all numbers above are stub timings)_
