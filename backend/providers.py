"""Model adapters.

Real providers speak the OpenAI-compatible HTTP API (vLLM, NIM, llama.cpp, Ollama all do), so swapping a
runtime or a model is an env-var change, never a code change. Stub providers exist for UI work without a GPU;
every event they touch carries model_name = "stub (no inference performed)" so nothing can pass as live inference.
"""
import base64
import io
import json
import logging
import re
import time
import urllib.request
from functools import lru_cache

from openai import BadRequestError, OpenAI
from PIL import Image, ImageOps
from pydantic import BaseModel

from . import config
from .models import Confidence, EventType, Observation, ObservationList

log = logging.getLogger("rescuebase")

STUB_NAME = "stub (no inference performed)"

VISION_SYSTEM = """You are the vision analyst of RescueBase, a local incident-intelligence system at a disaster incident command post.
Examine the image and list distinct, operationally relevant observations, each typed as one of:
- ACCESS_BLOCKAGE: roads, paths or bridges that appear impassable (debris, landslide, water, collapse).
- STRUCTURAL_DAMAGE: damaged or collapsed buildings and structures.
- TERRAIN_CHANGE: landslides, flooding, debris fields, erosion, changed river course.
- INFRASTRUCTURE_CONDITION: state of roads, bridges, power lines, telecom masts, dams, whether intact or not.
- OBJECT_OBSERVED: vehicles, equipment, people, animals, shelters. Describe people neutrally (count, activity, position). NEVER label anyone a victim, casualty or trapped person and never infer injuries.
- UNCERTAIN: features you cannot identify with reasonable confidence.
Rules: report only what is visible. No speculation about causes, casualties, or anything outside the frame. One observation per distinct feature, 1-2 sentences each, 1 to 6 observations total. Confidence HIGH only when unambiguous, otherwise MEDIUM or LOW. region_hint = position in the frame (e.g. "lower-left, along the river"). Respond with JSON only, matching the provided schema."""

REPORT_SYSTEM = """You are the report analyst of RescueBase, a local incident-intelligence system at a disaster incident command post.
The user message is a transcript of responder radio audio or a field text report (it may be a SIMULATED training report). Extract each distinct reported observation as a separate event:
- REPORTED_EVENT for things the speaker reports (team position, resource request, sighting, status).
- ACCESS_BLOCKAGE / STRUCTURAL_DAMAGE / TERRAIN_CHANGE / INFRASTRUCTURE_CONDITION when the report is specifically about that.
- UNCERTAIN when the audio is garbled or the meaning is unclear.
Quote place names, sector names, times, call-signs and counts exactly as stated. Do not add facts that were not stated and do not infer casualties. 1 to 8 observations. Respond with JSON only, matching the provided schema."""

QUERY_SYSTEM = """You are RescueBase, a local incident-intelligence assistant answering an incident commander.
Answer the question using ONLY the evidence events listed in the user message. Cite evidence inline with the event id in square brackets, e.g. [ev_1a2b3c4d5e]. Distinguish HUMAN_CONFIRMED evidence from unconfirmed AI_CANDIDATE observations. If the evidence does not answer the question, say exactly what is missing. Never declare victims or casualties, never dispatch teams, never assign medical priority: humans make those decisions. Plain text, at most 120 words."""

SITREP_SYSTEM = """You are RescueBase preparing a low-bandwidth situation report for transmission over a constrained link.
Use ONLY the evidence events listed. Plain text, at most 160 words, exactly three sections:
CONFIRMED: HUMAN_CONFIRMED events.
UNCONFIRMED CANDIDATES: AI_CANDIDATE / UNVERIFIED events, explicitly marked unconfirmed.
GAPS: sectors or questions with no evidence.
Cite each item with its event id in square brackets. No recommendations, no dispatch orders, no casualty claims."""


def strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def extract_json(text: str) -> dict:
    """Pull the JSON object out of a model reply (tolerates <think> blocks and ``` fences)."""
    text = strip_think(text)
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"no JSON object in model output: {text[:200]!r}")
    return json.loads(text[start : end + 1])


@lru_cache(maxsize=8)
def _client(base_url: str, timeout: float = 180) -> OpenAI:
    return OpenAI(base_url=base_url, api_key="local", timeout=timeout, max_retries=0)


def _chat(base_url: str, model: str, messages: list, schema: type[BaseModel] | None = None) -> str:
    kw = dict(
        model=model,
        messages=messages,
        temperature=0,
        max_tokens=4000 if config.THINKING else 1200,
        extra_body={"chat_template_kwargs": {"enable_thinking": config.THINKING}},
    )
    if schema is not None:
        fmt = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()}}
        try:
            r = _client(base_url).chat.completions.create(**kw, response_format=fmt)
            return r.choices[0].message.content or ""
        except BadRequestError as e:  # server without json_schema support: fall back to prompt-only JSON
            log.warning("%s rejected json_schema response_format (%s); retrying unconstrained", base_url, e)
    r = _client(base_url).chat.completions.create(**kw)
    return r.choices[0].message.content or ""


def _structured(base_url: str, model: str, messages: list, schema: type[BaseModel]) -> BaseModel:
    return schema.model_validate(extract_json(_chat(base_url, model, messages, schema)))


def image_data_url(data: bytes) -> str:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((config.MAX_IMAGE_PX, config.MAX_IMAGE_PX))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


_probe_cache: dict[str, tuple[float, str]] = {}


def probe(base_url: str) -> str:
    """READY if the OpenAI-compatible server answers /models within 2s. Cached 5s (the UI polls)."""
    hit = _probe_cache.get(base_url)
    if hit and time.time() - hit[0] < 5:
        return hit[1]
    try:
        _client(base_url, 2).models.list()
        status = "READY"
    except Exception:
        status = "UNAVAILABLE"
    _probe_cache[base_url] = (time.time(), status)
    return status


# ---------------------------------------------------------------- real providers


class Vision:
    name = f"{config.VLM_MODEL} @ {config.VLM_URL}"

    def analyze_image(self, data: bytes, context: str = "") -> ObservationList:
        msgs = [
            {"role": "system", "content": VISION_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": context or "Analyze this image."},
                {"type": "image_url", "image_url": {"url": image_data_url(data)}},
            ]},
        ]
        return _structured(config.VLM_URL, config.VLM_MODEL, msgs, ObservationList)

    def health(self) -> str:
        return probe(config.VLM_URL)


class Reasoning:
    name = f"{config.LLM_MODEL} @ {config.LLM_URL}"

    def structured(self, system: str, user: str, schema: type[BaseModel]) -> BaseModel:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return _structured(config.LLM_URL, config.LLM_MODEL, msgs, schema)

    def complete(self, system: str, user: str) -> str:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return strip_think(_chat(config.LLM_URL, config.LLM_MODEL, msgs))

    def health(self) -> str:
        return probe(config.LLM_URL)


class Speech:
    name = f"{config.STT_MODEL} @ {config.STT_URL}"

    def transcribe(self, data: bytes, filename: str) -> str:
        r = _client(config.STT_URL).audio.transcriptions.create(model=config.STT_MODEL, file=(filename, data))
        return r.text.strip()

    def health(self) -> str:
        return probe(config.STT_URL)


class Embedding:
    name = f"{config.EMBED_MODEL} @ {config.EMBED_URL}"

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        """None when the embedding server is down: callers degrade to keyword retrieval (fail downward)."""
        try:
            r = _client(config.EMBED_URL, 30).embeddings.create(model=config.EMBED_MODEL, input=texts)
            return [d.embedding for d in r.data]
        except Exception as e:
            log.warning("embeddings unavailable (%s); keyword retrieval only", e)
            return None

    def health(self) -> str:
        return probe(config.EMBED_URL)


# ---------------------------------------------------------------- stubs (no inference, labelled as such)


def _stub_obs(text: str) -> ObservationList:
    return ObservationList(observations=[Observation(event_type=EventType.UNCERTAIN, observation=text, confidence=Confidence.UNKNOWN)])


class StubVision:
    name = STUB_NAME

    def analyze_image(self, data: bytes, context: str = "") -> ObservationList:
        w, h = Image.open(io.BytesIO(data)).size
        return _stub_obs("STUB PROVIDER: no local vision model configured, so no visual analysis was performed. "
                         f"Image received: {w}x{h} px, {len(data) // 1024} KB.")

    def health(self) -> str:
        return "STUB"


class StubReasoning:
    name = STUB_NAME

    def structured(self, system: str, user: str, schema: type[BaseModel]) -> BaseModel:
        return _stub_obs(f"STUB PROVIDER: no reasoning model configured; input stored unanalyzed: {user[:300]}")

    def complete(self, system: str, user: str) -> str:
        return "STUB PROVIDER: no reasoning model configured. Showing retrieved evidence only; no synthesis was performed."

    def health(self) -> str:
        return "STUB"


class StubSpeech:
    name = STUB_NAME

    def transcribe(self, data: bytes, filename: str) -> str:
        return f"STUB PROVIDER: no speech model configured; audio {filename!r} ({len(data) // 1024} KB) was stored but not transcribed."

    def health(self) -> str:
        return "STUB"


class StubEmbedding:
    name = STUB_NAME

    def embed(self, texts: list[str]) -> None:
        return None

    def health(self) -> str:
        return "STUB"


def build():
    """(vision, reasoning, speech, embedding) per RESCUEBASE_PROVIDER."""
    if config.PROVIDER == "stub":
        return StubVision(), StubReasoning(), StubSpeech(), StubEmbedding()
    return Vision(), Reasoning(), Speech(), Embedding()


# ---------------------------------------------------------------- external network state

_net: tuple[float, str] = (0.0, "UNKNOWN")


def network_state() -> str:
    """ONLINE if an HTTP GET of RESCUEBASE_NET_PROBE returns a status < 400 within 2s. Cached 3s.

    A bare TCP connect is not enough: VPNs, sandboxes and transparent proxies complete the handshake locally, so an
    unplugged cable would still read ONLINE. Requiring a real HTTP response from an external host fixes that.
    """
    global _net
    if time.time() - _net[0] < 3:
        return _net[1]
    try:
        with urllib.request.urlopen(config.NET_PROBE, timeout=2) as r:
            state = "ONLINE" if r.status < 400 else "OFFLINE"
    except Exception:
        state = "OFFLINE"
    _net = (time.time(), state)
    return state
