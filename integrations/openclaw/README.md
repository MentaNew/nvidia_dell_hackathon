# Sponsor component: OpenClaw agent writing source-linked incident updates

Chosen component: **OpenClaw** (the agent runtime that NemoClaw wraps in OpenShell). It is the smallest documented
path that does real work with zero cloud inference: a local OpenClaw agent, whose only model is the GB10's own vLLM
endpoint, runs the `rescuebase-log` skill to read events awaiting review from the local API and post one
source-linked draft update back. The update appears in the UI under "Incident updates" with the agent name, the
model, the time, and every cited event id linked to its evidence. People confirm or reject it like any event.

Status: files ready and the API side is tested with stubs. **Not yet executed on the GB10** (this laptop has no
OpenClaw and no local model). Steps below are from the official docs (12 Sep 2026); verify each on the box.

## Install on the GB10 (10 min, needs internet once)

```bash
# Node 24.16+ (the installer provisions Node 24 LTS when missing)
curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard
mkdir -p ~/.openclaw/workspace/skills
cp -r integrations/openclaw/skills/rescuebase-log ~/.openclaw/workspace/skills/
cp integrations/openclaw/openclaw.json5 ~/.openclaw/openclaw.json   # check baseUrl (:8001) and model id (qwen3-vl)
```

vLLM must expose tool calling for the agent loop (added in `scripts/serve_models.sh vlm`):
`--enable-auto-tool-choice --tool-call-parser hermes`.

## Verify (this is the evidence for the submission)

```bash
python3 ~/.openclaw/workspace/skills/rescuebase-log/scripts/rb.py candidates      # API reachable, events listed
openclaw agent --agent main --local --session-id rb-smoke --json \
  -m "Use the rescuebase-log skill: run its candidates command and reply with the count."
integrations/openclaw/run_update.sh                                                # posts an update
curl -s http://127.0.0.1:8000/api/updates | head -c 800                            # agent, model_name, cited_event_ids
```

Proof of no cloud: `grep -Ei "openai.com|anthropic|nvidia.com|googleapis" ~/.openclaw/openclaw.json` prints nothing;
`models.mode: "replace"` removes every built-in provider; while a turn runs, `ss -tnp | grep -E ':8001|:8000'` shows
only loopback connections. Keep the run log: `data/logs/openclaw.log`.

## Schedule (always-on)

`crontab -e` → `*/5 * * * * /home/<user>/rescuebase/integrations/openclaw/run_update.sh`
or, with the OpenClaw gateway running and `cron.enabled: true`:
`openclaw automations create "*/5 * * * *" "Use the rescuebase-log skill …" --name rb-update --session isolated`.

## Boundaries

The agent gets `exec` + `read` only (no write/edit/web tools). The skill script talks to loopback only. Updates are
drafts (`AI_CANDIDATE`); the server rejects an update that cites no existing event. Nothing in the log can authorize a
tool call: the script strips events down to their data fields before the agent sees them.

## Stretch: NemoClaw / OpenShell wrapper (only if >45 min remain)

`curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash`, then
`NEMOCLAW_PROVIDER=custom NEMOCLAW_ENDPOINT_URL=http://localhost:8000/v1 NEMOCLAW_MODEL=qwen3-vl NEMOCLAW_COMPATIBLE_AUTH_MODE=none nemoclaw onboard --non-interactive`.
Gotchas found in the docs: the interactive quickstart defaults to NVIDIA *cloud* endpoints (must choose local);
no-auth endpoints are only accepted on loopback ports 8000/11434/11435 (our vLLM is on :8001, so add `--api-key`);
the sandbox cannot reach `127.0.0.1` (use `host.openshell.internal` plus a network-policy entry); Spark ships Node 18
(needs 22.16+). Expect ~17 min for onboarding.
