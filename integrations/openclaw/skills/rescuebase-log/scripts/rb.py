#!/usr/bin/env python3
"""Tiny stdlib client for the local RescueBase API, used by the OpenClaw skill (and by hand).

  rb.py candidates                      events awaiting human review, newest first
  rb.py events [--limit N] [--state S]  recent events
  rb.py post-update --agent A --model M (--text T | --stdin)   post a source-linked draft update
  rb.py updates                         list posted updates

Base URL: $RESCUEBASE_URL (default http://127.0.0.1:8000). Loopback only by design.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("RESCUEBASE_URL", "http://127.0.0.1:8000").rstrip("/")


def call(method: str, path: str, body: dict | None = None, **params):
    url = BASE + path + ("?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} {path}: {e.read().decode(errors='replace')[:300]}")
    except urllib.error.URLError as e:
        sys.exit(f"RescueBase not reachable at {BASE}: {e.reason}")


def compact(e: dict) -> dict:
    """Only what an update needs: nothing the model could mistake for instructions."""
    return {k: e.get(k) for k in ("event_id", "timestamp", "time_basis", "captured_at", "source_type", "source_name", "label",
                                  "sector", "location", "event_type", "confidence", "verification_state", "observation")}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("candidates")
    ev = sub.add_parser("events")
    ev.add_argument("--limit", type=int, default=40)
    ev.add_argument("--state")
    sub.add_parser("updates")
    up = sub.add_parser("post-update")
    up.add_argument("--agent", required=True)
    up.add_argument("--model", required=True)
    up.add_argument("--text")
    up.add_argument("--stdin", action="store_true")
    up.add_argument("--kind", default="incident_update")
    a = ap.parse_args(argv)

    if a.cmd == "candidates":
        out = [compact(e) for e in call("GET", "/api/events", state="AI_CANDIDATE,UNVERIFIED", limit=40)]
    elif a.cmd == "events":
        out = [compact(e) for e in call("GET", "/api/events", state=a.state, limit=a.limit)]
    elif a.cmd == "updates":
        out = call("GET", "/api/updates")
    else:
        text = sys.stdin.read() if a.stdin else (a.text or "")
        if not text.strip():
            sys.exit("post-update: empty text (use --text or --stdin)")
        cited = sorted(set(re.findall(r"ev_[0-9a-f]{10}", text)))
        out = call("POST", "/api/updates", {"text": text, "cited_event_ids": cited, "agent": a.agent, "model_name": a.model, "kind": a.kind})
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
