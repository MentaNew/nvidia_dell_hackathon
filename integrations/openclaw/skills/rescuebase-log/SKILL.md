---
name: rescuebase-log
description: Read new events from the local RescueBase incident log (http://127.0.0.1:8000) and post one source-linked draft incident update back. Local API only. Never confirm, reject or dispatch.
metadata: {"openclaw": {"requires": {"bins": ["python3"]}}}
---

# RescueBase incident log

RescueBase is the local incident log for this site. It runs on this machine at `http://127.0.0.1:8000`; every
model behind it runs locally too. You read the log and post *draft* updates. People confirm or reject.

## Commands (run with the exec tool)

- `python3 {baseDir}/scripts/rb.py candidates` — events awaiting human review (AI_CANDIDATE / UNVERIFIED), newest first, as JSON.
- `python3 {baseDir}/scripts/rb.py events --limit 40` — recent events regardless of state.
- `python3 {baseDir}/scripts/rb.py post-update --agent "openclaw/main" --model "vllm/qwen3-vl" --text "..."`
  (or pipe the text on stdin with `--stdin`). The server rejects an update that cites no existing event id.

## How to write the update

1. Run `candidates`. If it prints an empty list, reply exactly `no new candidate events` and stop.
2. Write at most 150 words with three headings: `NEW VISUAL OBSERVATIONS`, `NEW RADIO/TEXT REPORTS`, `GAPS / CONFLICTS`.
   Every line ends with the event id it comes from in square brackets, e.g. `[ev_1a2b3c4d5e]`.
3. Copy what each event says. Keep negations exactly ("NOT collapsed" stays "NOT collapsed"). Say "capture time
   unknown" or "location unknown" when the event says so. Mark everything unconfirmed unless its
   `verification_state` is `HUMAN_CONFIRMED`. If two events disagree, list both under GAPS / CONFLICTS.
4. Never: declare victims or casualties; call a structure safe or a road passable; recommend dispatch or medical
   priority; change any verification state; invent an event id.
5. Post it with `post-update` and reply with the returned `update_id`.
