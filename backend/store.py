"""Incident memory. MongoDB when reachable (preferred); otherwise SQLite (stdlib) with identical semantics.

Documents are plain dicts. Filters are top-level equality; a list value means "in". Hackathon scale
(hundreds of events), so SQLite filters/sorts in Python rather than growing a query language.
"""
import json
import logging
import sqlite3
import threading
from pathlib import Path

from . import config

log = logging.getLogger("rescuebase")

ID_FIELD = {"events": "event_id", "sources": "source_id", "transcripts": "source_id", "jobs": "job_id", "updates": "update_id"}


def _match(doc: dict, filt: dict) -> bool:
    for k, v in filt.items():
        if isinstance(v, list):
            if doc.get(k) not in v:
                return False
        elif doc.get(k) != v:
            return False
    return True


class SqliteStore:
    kind = "sqlite"

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()  # ponytail: one global lock; a single command post never needs more
        self.db.execute("CREATE TABLE IF NOT EXISTS docs (coll TEXT, id TEXT, incident TEXT, body TEXT, PRIMARY KEY (coll, id))")
        self.db.commit()

    def health(self) -> str:
        return "READY"

    def insert(self, coll: str, doc: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO docs VALUES (?,?,?,?)",
                            (coll, doc[ID_FIELD[coll]], doc.get("incident_id"), json.dumps(doc)))
            self.db.commit()

    def find(self, coll: str, filt: dict | None = None, sort_key: str = "timestamp", desc: bool = True, limit: int = 500) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT body FROM docs WHERE coll=?", (coll,)).fetchall()
        docs = [d for d in (json.loads(r[0]) for r in rows) if _match(d, filt or {})]
        docs.sort(key=lambda d: d.get(sort_key) or "", reverse=desc)
        return docs[:limit]

    def get(self, coll: str, doc_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT body FROM docs WHERE coll=? AND id=?", (coll, doc_id)).fetchone()
        return json.loads(row[0]) if row else None

    def update(self, coll: str, doc_id: str, patch: dict) -> dict | None:
        doc = self.get(coll, doc_id)
        if doc is None:
            return None
        doc.update(patch)
        self.insert(coll, doc)
        return doc

    def clear(self, incident_id: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM docs WHERE incident=?", (incident_id,))
            self.db.commit()


class MongoStore:
    kind = "mongo"

    def __init__(self, url: str, dbname: str):
        from pymongo import MongoClient

        self.client = MongoClient(url, serverSelectionTimeoutMS=1500)
        self.client.admin.command("ping")  # raises if unreachable -> caller falls back to SQLite
        self.db = self.client[dbname]
        for coll, idf in ID_FIELD.items():
            self.db[coll].create_index(idf, unique=True)
            self.db[coll].create_index("incident_id")

    def health(self) -> str:
        try:
            self.client.admin.command("ping")
            return "READY"
        except Exception:
            return "UNAVAILABLE"

    def insert(self, coll: str, doc: dict) -> None:
        self.db[coll].replace_one({ID_FIELD[coll]: doc[ID_FIELD[coll]]}, dict(doc), upsert=True)

    def find(self, coll: str, filt: dict | None = None, sort_key: str = "timestamp", desc: bool = True, limit: int = 500) -> list[dict]:
        q = {k: ({"$in": v} if isinstance(v, list) else v) for k, v in (filt or {}).items()}
        return list(self.db[coll].find(q, {"_id": 0}).sort(sort_key, -1 if desc else 1).limit(limit))

    def get(self, coll: str, doc_id: str) -> dict | None:
        return self.db[coll].find_one({ID_FIELD[coll]: doc_id}, {"_id": 0})

    def update(self, coll: str, doc_id: str, patch: dict) -> dict | None:
        self.db[coll].update_one({ID_FIELD[coll]: doc_id}, {"$set": patch})
        return self.get(coll, doc_id)

    def clear(self, incident_id: str) -> None:
        for coll in ID_FIELD:
            self.db[coll].delete_many({"incident_id": incident_id})


def open_store():
    if config.MONGO_URL:
        try:
            store = MongoStore(config.MONGO_URL, config.MONGO_DB)
            log.info("incident memory: mongo %s/%s", config.MONGO_URL, config.MONGO_DB)
            return store
        except Exception as e:
            log.warning("mongo unavailable at %s (%s) -> SQLite fallback", config.MONGO_URL, e)
    log.info("incident memory: sqlite %s", config.SQLITE_PATH)
    return SqliteStore(config.SQLITE_PATH)
