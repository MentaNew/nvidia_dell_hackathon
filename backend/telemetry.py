"""Live GB10 telemetry.

Hardware readings (nvidia-smi, procfs) are reported ONLY when the server detects it is running on the GB10 (by the
nvidia-smi GPU name, or the explicit override RESCUEBASE_ASSUME_GB10=1, which only unlocks real readings and never
invents them). Anywhere else, and for any field a tool reports as N/A, the value is None -> the page shows
"Unavailable — awaiting GB10 telemetry", never a zero. The GB10 has one unified memory pool, so exactly one memory
figure is reported (nvidia-smi if it reports it, else procfs), never RAM and VRAM side by side.

A 1 Hz sampler keeps 3 minutes of history in this process, so graphs survive page navigation. Job start/end markers
and model-call spans let a viewer connect GPU activity to vision or transcription work.
"""
import logging
import os
import platform
import shutil
import socket
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from . import config, providers
from .models import now_iso

log = logging.getLogger("rescuebase")

UNAVAILABLE = "Unavailable — awaiting GB10 telemetry"
NOTES = ["Hardware telemetry (nvidia-smi / procfs readings, unified-memory figure) is UNVERIFIED on a GB10 as of 2026-09-12: "
         "only the parsers, the unavailable path and the graphs were tested on a laptop with stub providers."]
STARTED_AT, _T0 = now_iso(), time.time()
GPU_FIELDS = ["name", "driver_version", "memory.used", "memory.total", "utilization.gpu", "temperature.gpu", "power.draw"]
SAMPLES: deque = deque(maxlen=180)  # 1 Hz, 3 minutes
JOBS: deque = deque(maxlen=300)  # job start / end markers
_sampler_lock = threading.Lock()
_sampler_on = False


# ---------------------------------------------------------------- readings
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


def detection(gpu: dict | None) -> dict:
    """How we decided whether this host is the GB10. Transparent and overridable; the override adds no readings."""
    override = os.environ.get("RESCUEBASE_ASSUME_GB10") == "1"
    name = (gpu or {}).get("name")
    by_name = bool(name and "GB10" in name.upper())
    return {"detected": by_name or override,
            "method": "nvidia-smi GPU name" if by_name else ("override RESCUEBASE_ASSUME_GB10=1" if override else "none"),
            "nvidia_smi_present": bool(shutil.which("nvidia-smi")), "nvidia_smi_name": name, "override_active": override,
            "override_hint": "RESCUEBASE_ASSUME_GB10=1 unlocks real nvidia-smi/procfs readings when the GPU name differs; it never invents values"}


def gb10_detected(gpu: dict | None) -> bool:
    return detection(gpu)["detected"]


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


def unified_memory(gpu: dict | None, system: dict | None) -> dict | None:
    """The GB10's single unified pool: nvidia-smi if it reports it, else procfs. Never both, never zero-filled."""
    if gpu and gpu.get("memory.used") is not None and gpu.get("memory.total"):
        return {"used_mib": gpu["memory.used"], "total_mib": gpu["memory.total"],
                "pct": round(100 * gpu["memory.used"] / gpu["memory.total"], 1), "source": "nvidia-smi (unified memory)"}
    if system and system.get("ram_used_mib") is not None and system.get("ram_total_mib"):
        return {"used_mib": system["ram_used_mib"], "total_mib": system["ram_total_mib"],
                "pct": round(100 * system["ram_used_mib"] / system["ram_total_mib"], 1),
                "source": "procfs (unified memory; nvidia-smi reports N/A)"}
    return None


# ---------------------------------------------------------------- sampler, markers, history
def kind_for(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"):
        return "transcription"
    if ext in (".txt", ".md", ".csv", ".log"):
        return "report"
    return "vision"


def mark_job(job_id: str, name: str, phase: str, status: str | None = None, duration_s: float | None = None,
             drop_to_entry_s: float | None = None, events: int | None = None) -> None:
    JOBS.append({"t": round(time.time(), 3), "job": job_id, "name": name, "kind": kind_for(name), "phase": phase,
                 "status": status, "duration_s": duration_s, "drop_to_entry_s": drop_to_entry_s, "events": events})


def sample_once(worker=None) -> dict:
    gpu = query_gpu()
    on = detection(gpu)["detected"]
    sysr = system_readings() if on else None
    mem = unified_memory(gpu, sysr) if on else None
    g = gpu if (on and gpu) else {}
    return {"t": round(time.time(), 3), "gb10": on, "gpu_util": g.get("utilization.gpu"), "temp_c": g.get("temperature.gpu"),
            "power_w": g.get("power.draw"), "mem_pct": mem["pct"] if mem else None, "mem_used_mib": mem["used_mib"] if mem else None,
            "mem_total_mib": mem["total_mib"] if mem else None, "mem_source": mem["source"] if mem else None,
            "queue": worker.q.qsize() if worker else None, "active": len(worker.active) if worker else None}


def start_sampler(get_worker) -> None:
    """1 Hz background sampling for the life of the process (history survives page navigation)."""
    global _sampler_on
    with _sampler_lock:
        if _sampler_on:
            return
        _sampler_on = True

    def loop():
        while True:
            t0 = time.time()
            try:
                SAMPLES.append(sample_once(get_worker()))
            except Exception as e:
                log.warning("telemetry sample failed: %s", e)
            time.sleep(max(0.2, 1 - (time.time() - t0)))

    threading.Thread(target=loop, name="telemetry-sampler", daemon=True).start()


def history(seconds: int = 60) -> dict:
    seconds = max(5, min(seconds, 180))
    cutoff = time.time() - seconds
    calls = {k: [[round(ts, 3), s] for ts, s in list(v["latencies"]) if ts >= cutoff] for k, v in providers.LAST.items()}
    return {"now": round(time.time(), 3), "seconds": seconds, "hz": 1, "gb10": bool(SAMPLES and SAMPLES[-1]["gb10"]),
            "provider_mode": config.PROVIDER, "samples": [s for s in SAMPLES if s["t"] >= cutoff], "calls": calls,
            "jobs": [j for j in JOBS if j["t"] >= cutoff]}


# ---------------------------------------------------------------- snapshot (tiles)
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
    det = detection(gpu)
    on_gb10 = det["detected"]
    sysr = system_readings() if on_gb10 else None
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
    gpu_view = ({k: v for k, v in gpu.items() if k not in ("memory.used", "memory.total")} if (on_gb10 and gpu) else None)
    return {
        "served_at": now_iso(),
        "host": {"hostname": socket.gethostname(), "platform": platform.platform(), "gb10_detected": on_gb10, "detection": det,
                 "server_started_at": STARTED_AT, "uptime_s": int(time.time() - _T0), "provider_mode": config.PROVIDER,
                 "history_samples": len(SAMPLES)},
        "gpu": gpu_view,
        "memory": unified_memory(gpu, sysr) if on_gb10 else None,
        "system": {"load_1m": sysr["load_1m"], "cpus": sysr["cpus"]} if sysr else None,
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
