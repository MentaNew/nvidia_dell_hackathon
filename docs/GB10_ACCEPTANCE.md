# GB10 deployment and acceptance runbook

Goal: first real result within 30 minutes of access; then a PASS / FAIL / NOT RUN table for the six paths with
measured latency and memory. No new features, no model experiments. Everything below runs on the GB10 itself.

## A. Deploy (needs internet once; ~15 min)

```bash
git clone https://github.com/MentaNew/nvidia_dell_hackathon.git rescuebase && cd rescuebase   # or git pull
sudo apt install -y python3-venv                 # only if scripts/run.sh complains about venv
scripts/gb10_checklist.sh                        # GPU, disks, SSD mount, ports, internet probe
export RESCUEBASE_MODEL_ROOT=/mnt/<ssd>/GB10_ARSENAL/models   # from the checklist output
scripts/serve_models.sh vlm                      # terminal 1: Qwen3-VL on :8001   (wait for "Uvicorn running")
scripts/serve_models.sh stt                      # terminal 2: Whisper on :8003
curl -s localhost:8001/v1/models | head -c 300; curl -s localhost:8003/v1/models | head -c 300
cp .env.example .env                             # RESCUEBASE_PROVIDER=openai
scripts/run.sh                                   # terminal 3: app + inbox worker on :8000
```
Open http://localhost:8000 on the GB10: header must read `LOCAL INFERENCE: ENDPOINT UP · no successful run yet`.
If a vLLM flag is rejected, fix the flag in `scripts/serve_models.sh`; do not touch the app.

## B. First result (target: <30 min after access)

```bash
RESCUEBASE_TEST_IMAGE=/path/selected_site_image.jpg RESCUEBASE_TEST_AUDIO=/path/exercise_message.wav \
  .venv/bin/python tests/test_real.py
```
Prints the events, the transcript and a MEASUREMENTS block (hardware, latency). Read the transcript against what
was said and the events against the image before calling it a pass. Header flips to `LOCAL INFERENCE: OK · last run`.

## C. Acceptance, online phase (paths 1–5)

Install OpenClaw first if path 5 is wanted (needs internet): see `integrations/openclaw/README.md`.

```bash
.venv/bin/python scripts/gb10_acceptance.py --image /path/selected_site_image.jpg \
    --audio /path/exercise_message.wav --sector "Sector 4"
```
It re-runs `test_real.py` under a memory sampler, asks you two yes/no questions (path 3), drops FRESH variants of the
image and audio into the inbox (new bytes, so the worker cannot dedupe them) and times the running worker (path 4),
runs `integrations/openclaw/run_update.sh` and shows the posted update (path 5), and writes
`docs/ACCEPTANCE_<timestamp>.md`.

## D. Acceptance, offline phase (path 6)

Disconnect only the external uplink (unplug the WAN cable / disable the hotspot). Keep the LAN or work on the GB10's
own screen. Then:
```bash
.venv/bin/python scripts/gb10_acceptance.py --phase offline --audio /path/fresh_exercise_message.wav --sector "Sector 4"
```
The script waits until the header says `EXTERNAL INTERNET: OFFLINE`, drops a fresh message, waits for the real
transcript/event, and runs the sponsor action again. A separate recording (new identifier) is the strongest evidence.

## E. Record

Append the ACCEPTANCE report to `docs/STATUS_LOG.md` and commit (`git add docs && git commit -m "GB10 acceptance" && git push`
when the uplink is back). Report each path as PASS / FAIL / NOT RUN with the exact blocker.

## Common blockers

- `LOCAL INFERENCE: UNAVAILABLE`: vLLM not listening on :8001, or `RESCUEBASE_VLM_URL` differs. `curl localhost:8001/v1/models`.
- Whisper endpoint returns 400/415: transcode is already done server-side (16 kHz WAV); check the vLLM whisper flags
  (`--task transcription` on older vLLM) or run `speaches`/faster-whisper on :8003 instead.
- Both servers loaded but the second one OOMs: lower `--gpu-memory-utilization` in `scripts/serve_models.sh`; the
  fractions are configuration, not proof.
- Worker "never seen": the file landed outside `data/inbox` or has a skipped suffix (`.json .tmp .part .md`).
- Probe stays ONLINE after unplugging: the LAN still routes to the internet, or a proxy answers; set
  `RESCUEBASE_NET_PROBE` to an external URL that really goes away.
- `openclaw` missing: install step skipped; path 5/6b stay NOT RUN, everything else is unaffected.
