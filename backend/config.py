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

NET_PROBE = _get("NET_PROBE", "1.1.1.1:443")  # TCP connect target that defines "external network"
MAP_BOUNDS = _get("MAP_BOUNDS", "")  # "min_lon,min_lat,max_lon,max_lat" georeferencing data/map.png
