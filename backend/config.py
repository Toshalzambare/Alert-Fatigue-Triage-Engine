"""Central config. Everything that varies lives here, read from env with working defaults.

Plan 05 Phase 4. Nothing else in the backend should call os.environ directly.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# --- Elastic Cloud (contract: managed Elastic, not local Docker) ---
ES_CLOUD_ID = env("ES_CLOUD_ID", "")
ES_API_KEY = env("ES_API_KEY", "")
ES_INDEX = env("ES_INDEX", "secops-logs-*")

# --- MCP (contract §5: HTTP transport for a repo submission) ---
MCP_MODE = env("MCP_MODE", "http")  # http | stdio
MCP_URL = env("MCP_URL", "http://localhost:8000/mcp")

# --- Gemma ---
# NOTE: runtime still undecided (local Ollama vs hosted). Placeholder default.
GEMMA_MODEL = env("GEMMA_MODEL", "gemma-4-12b-it")
GEMMA_LOADED = False  # flipped by the agent module once a model is actually resident

# --- Server ---
PORT = env_int("PORT", 5001)  # 5000 is taken by macOS AirPlay Receiver
HOST = env("HOST", "127.0.0.1")
DEBUG = env_bool("DEBUG", True)

# Vite dev server origins. "*" is fine for a local demo; narrow it if the
# backend is ever exposed beyond localhost.
CORS_ORIGINS = env("CORS_ORIGINS", "*")

# --- Demo controls ---
DEMO_REPLAY = env_bool("DEMO_REPLAY", False)  # the escape hatch (Phase 5)
MOCK_EVENTS = env("MOCK_EVENTS", "mock_events.jsonl")
MOCK_DELAY_MS = env_int("MOCK_DELAY_MS", 300)  # pacing between replayed events

# --- Streaming ---
STREAM_TIMEOUT_S = env_int("STREAM_TIMEOUT_S", 120)  # never q.get() unbounded
HEARTBEAT_S = env_int("HEARTBEAT_S", 15)  # SSE keepalive comment interval

# --- Uploads ---
MAX_UPLOAD_MB = env_int("MAX_UPLOAD_MB", 10)


def mode() -> str:
    """What the demo is currently wired to. Surfaced by /api/health.

    GEMMA_LOADED is flipped by agent_bridge once D's graph imports cleanly, so
    this reflects reality rather than intent.
    """
    if DEMO_REPLAY:
        return "replay"
    return "live" if GEMMA_LOADED else "mock"


def summary() -> dict:
    """Non-secret config echo for /api/health. Never include ES_API_KEY."""
    return {
        "mode": mode(),
        "es_index": ES_INDEX,
        "es_configured": bool(ES_CLOUD_ID and ES_API_KEY),
        "mcp_mode": MCP_MODE,
        "mcp_url": MCP_URL,
        "gemma_model": GEMMA_MODEL,
        "demo_replay": DEMO_REPLAY,
        "port": PORT,
    }
