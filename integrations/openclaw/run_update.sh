#!/usr/bin/env bash
# One local OpenClaw agent turn: read new candidate events from RescueBase and post a source-linked draft update.
# Everything stays on this machine (OpenClaw + local vLLM). Schedule it, e.g.:  */5 * * * *  /path/to/run_update.sh
set -euo pipefail
export RESCUEBASE_URL=${RESCUEBASE_URL:-http://127.0.0.1:8000}
LOG=${RESCUEBASE_AGENT_LOG:-$(dirname "$0")/../../data/logs/openclaw.log}
mkdir -p "$(dirname "$LOG")"
{
  echo "=== $(date -Is) run_update"
  openclaw agent --agent main --local --session-id "rb-$(date +%s)" --json \
    -m "Use the rescuebase-log skill: run its candidates command, write one source-linked incident update following the skill rules, post it with post-update, and reply with the returned update_id."
} | tee -a "$LOG"
