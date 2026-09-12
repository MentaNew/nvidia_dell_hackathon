"""Always-on ingestion: watch a local inbox and push settled files through Pipeline.ingest.

Identity is the content hash, persisted as a job in the store, so restarts never re-ingest completed inputs and the
same bytes under a new name are recorded as duplicate evidence, not as a new source. One failed input never blocks
the next; retries are bounded. Runs in daemon threads inside the API process: no browser, no extra service.
"""
import hashlib
import json
import logging
import queue
import threading
import time
from pathlib import Path

from . import config
from .models import Label, now_iso

log = logging.getLogger("rescuebase")

SKIP_SUFFIX = {".json", ".tmp", ".part", ".crdownload", ".md"}
SIDECAR_KEYS = {"sector", "label", "simulated", "note", "captured_at", "location"}
LABEL_DIRS = {name.lower(): name for name in Label.__members__}  # inbox/exercise/x.wav -> EXERCISE


def sidecar_meta(path: Path) -> dict:
    """Operator-supplied provenance: the label folder name, overridden by <file>.json next to the file."""
    meta: dict = {}
    if path.parent.name.lower() in LABEL_DIRS:
        meta["label"] = LABEL_DIRS[path.parent.name.lower()]
    sc = path.with_name(path.name + ".json")
    if sc.exists():
        try:
            meta.update({k: v for k, v in json.loads(sc.read_text(encoding="utf-8")).items() if k in SIDECAR_KEYS})
            if "captured_at" in meta:
                meta["captured_at_source"] = "sidecar"
        except Exception as e:
            log.warning("ignoring bad sidecar %s: %s", sc, e)
    return meta


class Worker:
    def __init__(self, pipe, inbox=None, settle_s=None, retries=None, queue_size=None, concurrency=None):
        self.pipe, self.store = pipe, pipe.store
        self.inbox = Path(inbox or config.INBOX_DIR)
        self.settle_s = config.INBOX_SETTLE_S if settle_s is None else settle_s
        self.retries = config.INGEST_RETRIES if retries is None else retries
        self.concurrency = concurrency or config.INFER_CONCURRENCY
        self.q: queue.Queue = queue.Queue(maxsize=queue_size or config.INBOX_QUEUE)
        self.seen: dict[str, tuple[int, float]] = {}  # path -> (size, mtime) at the previous scan: settle detection
        self.decided: set[tuple] = set()  # (path, size, mtime) already resolved against the jobs collection
        self.active: set[str] = set()  # job ids queued or processing in this process
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.started_at = self.last_scan = self.last_error = None

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.started_at = now_iso()
        self.threads = [threading.Thread(target=self._scan_loop, name="inbox-scan", daemon=True)]
        self.threads += [threading.Thread(target=self._work_loop, name=f"ingest-{i}", daemon=True) for i in range(self.concurrency)]
        for t in self.threads:
            t.start()
        log.info("inbox worker: watching %s (settle %.1fs, concurrency %d, retries %d)", self.inbox, self.settle_s,
                 self.concurrency, self.retries)

    def stop(self) -> None:
        self.stop_event.set()

    def reset(self) -> None:
        """Forget scan state (after a demo reset) so files dropped again are considered fresh."""
        with self.lock:
            self.seen.clear()
            self.decided.clear()

    def _scan_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.scan_once()
            except Exception as e:
                self.last_error = f"scan: {e}"
                log.exception("inbox scan failed")
            self.stop_event.wait(config.INBOX_SCAN_S)

    def _work_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                job = self.q.get(timeout=1)
            except queue.Empty:
                continue
            self.run_job(job)
            self.q.task_done()

    def drain(self) -> int:
        """Process everything queued, synchronously (tests and one-shot CLI use)."""
        n = 0
        while True:
            try:
                job = self.q.get_nowait()
            except queue.Empty:
                return n
            self.run_job(job)
            n += 1

    # ------------------------------------------------------------ scanning

    def _files(self):
        for p in sorted(self.inbox.rglob("*")):
            if p.is_file() and not p.name.startswith((".", "~", "_")) and p.suffix.lower() not in SKIP_SUFFIX:
                yield p

    def scan_once(self) -> int:
        """One pass over the inbox. Returns the number of jobs enqueued."""
        self.last_scan = now_iso()
        now, enqueued = time.time(), 0
        for p in self._files():
            try:
                st = p.stat()
            except OSError:
                continue
            key = (str(p), st.st_size, st.st_mtime)
            prev = self.seen.get(str(p))
            self.seen[str(p)] = (st.st_size, st.st_mtime)
            if key in self.decided:
                continue
            settled = st.st_size > 0 and prev == (st.st_size, st.st_mtime) and now - st.st_mtime >= self.settle_s
            if not settled:
                continue  # still being written (or just arrived): look again next scan
            outcome = self._consider(p, st.st_size, st.st_mtime)
            if outcome != "wait":
                self.decided.add(key)
            enqueued += outcome == "enqueued"
        return enqueued

    def _consider(self, p: Path, size: int, mtime: float) -> str:
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        job_id = "job_" + digest[:16]
        job = self.store.get("jobs", job_id)
        if job:
            if str(p) != job["path"] and str(p) not in job.get("duplicate_paths", []):
                # Same bytes under another name: duplicate evidence, not independent corroboration.
                self.store.update("jobs", job_id, {"duplicate_paths": job.get("duplicate_paths", []) + [str(p)],
                                                  "updated_at": now_iso()})
                log.info("inbox: %s duplicates %s (%s); not re-ingested", p.name, job["name"], job_id)
                return "skip"
            if job["status"] in ("completed", "failed"):
                return "skip"  # already resolved in a previous run
            # queued / processing / retrying left over from a crash: resume with attempts preserved
        else:
            dropped = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(mtime))  # file arrival: measures drop -> entry
            job = {"job_id": job_id, "incident_id": config.INCIDENT_ID, "path": str(p), "name": p.name, "bytes": size,
                   "sha256": digest, "status": "queued", "attempts": 0, "error": None, "source_id": None, "event_ids": [],
                   "duplicate_paths": [], "dropped_at": dropped, "created_at": now_iso(), "updated_at": now_iso()}
        return "enqueued" if self._enqueue(job) else "wait"

    def _patch(self, job: dict, patch: dict) -> dict:
        """Merge into the stored job (never replace: the scanner may record duplicate_paths concurrently)."""
        job.update(patch)
        if self.store.update("jobs", job["job_id"], patch) is None:
            self.store.insert("jobs", job)
        return job

    def _enqueue(self, job: dict) -> bool:
        with self.lock:
            if job["job_id"] in self.active:
                return False
            try:
                self.q.put_nowait(job)
            except queue.Full:
                log.warning("inbox queue full (%d); %s waits for a later scan", self.q.maxsize, job["name"])
                return False
            self.active.add(job["job_id"])
        self._patch(job, {"status": "queued", "updated_at": now_iso()})
        return True

    def _requeue(self, job: dict) -> None:
        if not self._enqueue(job):
            t = threading.Timer(5, self._requeue, [job])
            t.daemon = True
            t.start()

    # ------------------------------------------------------------ processing

    def run_job(self, job: dict) -> dict:
        job_id, p = job["job_id"], Path(job["path"])
        job = self.store.get("jobs", job_id) or job
        self._patch(job, {"status": "processing", "attempts": job["attempts"] + 1, "started_at": now_iso(), "updated_at": now_iso()})
        t0 = time.time()
        try:
            meta = sidecar_meta(p)
            r = self.pipe.ingest(p.name, p.read_bytes(), job_id=job_id, **meta)
            patch = {"status": "completed", "source_id": r["source"]["source_id"], "event_ids": [e["event_id"] for e in r["events"]],
                     "error": None, "duration_s": round(time.time() - t0, 2), "finished_at": now_iso(), "updated_at": now_iso()}
            log.info("inbox: %s -> %d event(s) in %.1fs", p.name, len(patch["event_ids"]), patch["duration_s"])
        except Exception as e:
            err = f"{type(e).__name__}: {getattr(e, 'detail', None) or str(e)[:300]}"
            retry = job["attempts"] <= self.retries
            patch = {"status": "retrying" if retry else "failed", "error": err, "duration_s": round(time.time() - t0, 2),
                     "updated_at": now_iso()}
            log.warning("inbox: %s failed (attempt %d/%d): %s", p.name, job["attempts"], self.retries + 1, err)
            if retry:
                t = threading.Timer(min(2 ** job["attempts"], 30), self._requeue, [job])
                t.daemon = True
                t.start()
        finally:
            with self.lock:
                self.active.discard(job_id)
        return self._patch(job, patch)

    # ------------------------------------------------------------ status

    def status(self) -> dict:
        jobs = self.store.find("jobs", {"incident_id": config.INCIDENT_ID}, sort_key="updated_at", limit=1000)
        counts = {s: 0 for s in ("queued", "processing", "retrying", "completed", "failed")}
        for j in jobs:
            counts[j["status"]] = counts.get(j["status"], 0) + 1
        # Business-value measurement: seconds from file arrival (mtime) to a saved, reviewable entry.
        t2e = sorted(_seconds_between(j.get("dropped_at"), j.get("finished_at")) for j in jobs if j["status"] == "completed")
        t2e = [x for x in t2e if x is not None]
        return {"enabled": True, "inbox": str(self.inbox), "running": any(t.is_alive() for t in self.threads),
                "started_at": self.started_at, "last_scan": self.last_scan, "last_error": self.last_error,
                "queue_size": self.q.qsize(), "concurrency": self.concurrency, "settle_s": self.settle_s,
                "retries": self.retries, "counts": counts, "recent": jobs[:15],
                "time_to_entry_s": {"n": len(t2e), "median": t2e[len(t2e) // 2] if t2e else None,
                                    "max": t2e[-1] if t2e else None}}


def _seconds_between(a: str | None, b: str | None) -> float | None:
    from datetime import datetime

    try:
        return round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds(), 1)
    except (TypeError, ValueError):
        return None
