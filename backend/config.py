"""Environment-driven configuration. Every knob is a RESCUEBASE_* env var; a repo-root .env is read as defaults."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ponytail: 6-line .env loader instead of python-dotenv; real env vars win
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.split("#", 1)[0].strip()
        if _line and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"'))


def _get(key: str, default: str = "") -> str:
    return os.environ.get(f"RESCUEBASE_{key}", default)


DATA_DIR = Path(_get("DATA_DIR", str(ROOT / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"
DEMO_DIR = DATA_DIR / "demo"
SQLITE_PATH = DATA_DIR / "rescuebase.db"

INCIDENT_ID = _get("INCIDENT", "demo-incident")
INCIDENT_NAME = _get("INCIDENT_NAME", "DEMO INCIDENT (simulated operational metadata)")
DEMO_MODE = _get("DEMO", "1") == "1"

MONGO_URL = _get("MONGO_URL", "mongodb://127.0.0.1:27017")  # "" -> SQLite only
MONGO_DB = _get("MONGO_DB", "rescuebase")

PROVIDER = _get("PROVIDER", "openai")  # openai = any OpenAI-compatible server (vLLM/NIM/llama.cpp/Ollama) | stub
VLM_URL = _get("VLM_URL", "http://127.0.0.1:8001/v1")
VLM_MODEL = _get("VLM_MODEL", "qwen3-vl")
LLM_URL = _get("LLM_URL", VLM_URL)  # default: reuse the VLM for reasoning until Nemotron is served
LLM_MODEL = _get("LLM_MODEL", VLM_MODEL)
STT_URL = _get("STT_URL", "http://127.0.0.1:8003/v1")
STT_MODEL = _get("STT_MODEL", "whisper-large-v3-turbo")
EMBED_URL = _get("EMBED_URL", "http://127.0.0.1:8004/v1")
EMBED_MODEL = _get("EMBED_MODEL", "nemotron-embed")
THINKING = _get("THINKING", "0") == "1"  # reasoning-model <think> mode; off for demo latency
MAX_IMAGE_PX = int(_get("MAX_IMAGE_PX", "1280"))  # images are downscaled to this before the VLM sees them

NET_PROBE = _get("NET_PROBE", "http://connectivitycheck.gstatic.com/generate_204")  # HTTP URL that defines "external network"
MAP_BOUNDS = _get("MAP_BOUNDS", "")  # "min_lon,min_lat,max_lon,max_lat" georeferencing data/map.png

# Always-on ingestion: files dropped into the inbox (or a label subfolder: inbox/exercise, inbox/replay, ...) are
# processed automatically once they stop changing. Identity is the content hash, persisted in the store.
INBOX_ENABLED = _get("INBOX_ENABLED", "1") == "1"
INBOX_DIR = Path(_get("INBOX", str(DATA_DIR / "inbox")))
INBOX_SCAN_S = float(_get("INBOX_SCAN_S", "2"))  # seconds between inbox scans
INBOX_SETTLE_S = float(_get("INBOX_SETTLE_S", "2"))  # a file must be unchanged this long before it is read
INBOX_QUEUE = int(_get("INBOX_QUEUE", "32"))  # bounded queue; extra files wait for the next scan
INFER_CONCURRENCY = int(_get("INFER_CONCURRENCY", "1"))  # ingest workers = concurrent model calls
INGEST_RETRIES = int(_get("INGEST_RETRIES", "2"))  # retries after the first failed attempt
INBOX_DEFAULT_LABEL = _get("INBOX_DEFAULT_LABEL", "UNKNOWN")  # LIVE | REPLAY | ARCHIVAL | EXERCISE | SATELLITE | UNKNOWN

# Recorded-replay video: sample one frame every N seconds for inference (playback itself is real time)
FRAME_INTERVAL_S = float(_get("FRAME_INTERVAL_S", "10"))
FRAME_MAX = int(_get("FRAME_MAX", "12"))
