"""Live GB10 telemetry.

Hardware readings (nvidia-smi, procfs) are reported ONLY when the server detects it is running on the GB10;
anywhere else they are "Unavailable — awaiting GB10 telemetry". Laptop numbers are never substituted.
Application counters (inference latency, ingestion throughput, log counts) describe this process, and the payload
says which host produced them and whether its providers are stubs.
"""
import os
import platform
import shutil
import socket
import subprocess
import time
from datetime import datetime, timedelta, timezone
from statistics import median

from . import config, providers
from .models import now_iso

UNAVAILABLE = "Unavailable — awaiting GB10 telemetry"
NOTES = ["Hardware telemetry path (nvidia-smi / procfs) is NOT TESTED on the GB10 as of 2026-09-12: only the parser and the "
         "unavailable path were tested on a laptop."]
STARTED_AT, _T0 = now_iso(), time.time()
GPU_FIELDS = ["name", "driver_version", "memory.used", "memory.total", "utilization.gpu", "temperature.gpu", "power.draw"]


def parse_nvidia_smi(line: str) -> dict:
    """One CSV line of `nvidia-smi --query-gpu=<GPU_FIELDS> --format=csv,noheader,nounits`; '[N/A]' -> None."""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != len(GPU_FIELDS):
        raise ValueError(f"expected {len(GPU_FIELDS)} fields, got {len(parts)}: {line!r}")
    out: dict = {}
    for k, v in zip(GPU_FIELDS, parts):
        if k in ("name", "driver_version"):
            out[k] = v
        else:
            try:
                out[k] = float(v)
            except ValueError:
                out[k] = None
    return out


def query_gpu() -> dict | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(["nvidia-smi", f"--query-gpu={','.join(GPU_FIELDS)}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return parse_nvidia_smi(out.splitlines()[0]) if out else None
    except Exception:
        return None


def gb10_detected(gpu: dict | None) -> bool:
    if os.environ.get("RESCUEBASE_ASSUME_GB10") == "1":
        return True
    return bool(gpu and "GB10" in (gpu.get("name") or "").upper())


def system_readings() -> dict | None:
    """Linux procfs only (the GB10); None elsewhere."""
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                mem[k] = int(v.split()[0]) // 1024
        load = os.getloadavg()
        return {"ram_used_mib": mem["MemTotal"] - mem["MemAvailable"], "ram_total_mib": mem["MemTotal"],
                "load_1m": round(load[0], 2), "cpus": os.cpu_count()}
    except Exception:
        return None


def latency_stats(kind: str) -> dict | None:
    samples = list(providers.LAST[kind]["latencies"])
    if not samples:
        return None
    lat = sorted(s for _, s in samples)
    return {"count": len(lat), "last_s": round(samples[-1][1], 2), "p50_s": round(median(lat), 2),
            "p95_s": round(lat[int(0.95 * (len(lat) - 1))], 2), "max_s": round(lat[-1], 2)}


def _recent(jobs: list[dict], minutes: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    return [j for j in jobs if j.get("status") == "completed" and (j.get("finished_at") or "") >= cutoff]


def snapshot(pipe, worker) -> dict:
    gpu = query_gpu()
    on_gb10 = gb10_detected(gpu)
    health = pipe.health()
    inference = {}
    for k, p in health["providers"].items():
        note = None
        if p["endpoint"] == "STUB":
            note = "STUB providers on this host: no inference, no latency"
        elif p["endpoint"] != "READY":
            note = "endpoint unavailable"
        inference[k] = {**p, "latency": latency_stats(k) if p["endpoint"] == "READY" else None, "note": note}
    ing = worker.status() if worker else {"enabled": False, "running": False, "counts": {}, "recent": [], "queue_size": 0}
    jobs = pipe.store.find("jobs", {"incident_id": config.INCIDENT_ID}, sort_key="updated_at", limit=2000) if worker else []
    last10 = _recent(jobs, 10)
    durations = sorted(j["duration_s"] for j in last10 if j.get("duration_s") is not None)
    ing_summary = {"enabled": ing.get("enabled", False), "running": ing.get("running", False), "queue_size": ing.get("queue_size", 0),
                   "counts": ing.get("counts", {}), "time_to_entry_s": ing.get("time_to_entry_s"),
                   "completed_last_10min": len(last10), "per_minute_last_10min": round(len(last10) / 10, 2),
                   "processing_s_last_10min": {"p50": durations[len(durations) // 2], "max": durations[-1]} if durations else None,
                   "recent": [{"name": j["name"], "status": j["status"], "duration_s": j.get("duration_s"), "events": len(j.get("event_ids") or []),
                               "finished_at": j.get("finished_at"), "error": j.get("error")} for j in ing.get("recent", [])[:8]]}
    events = pipe.store.find("events", {"incident_id": config.INCIDENT_ID}, limit=20000)
    by_state: dict = {}
    by_type: dict = {}
    for e in events:
        by_state[e["verification_state"]] = by_state.get(e["verification_state"], 0) + 1
        by_type[e["source_type"]] = by_type.get(e["source_type"], 0) + 1
    return {
        "served_at": now_iso(),
        "host": {"hostname": socket.gethostname(), "platform": platform.platform(), "gb10_detected": on_gb10,
                 "nvidia_smi": bool(shutil.which("nvidia-smi")), "server_started_at": STARTED_AT, "uptime_s": int(time.time() - _T0),
                 "provider_mode": config.PROVIDER},
        "gpu": gpu if on_gb10 else None,
        "system": system_readings() if on_gb10 else None,
        "unavailable_reason": None if on_gb10 else UNAVAILABLE,
        "inference_state": health["inference"],
        "inference": inference,
        "ingestion": ing_summary,
        "network": health["network"],
        "store": {"kind": health["store"], "status": health["store_status"]},
        "log": {"events": len(events), "by_verification_state": by_state, "by_source_type": by_type,
                "updates": len(pipe.store.find("updates", {"incident_id": config.INCIDENT_ID}, limit=1000))},
        "notes": NOTES,
    }
