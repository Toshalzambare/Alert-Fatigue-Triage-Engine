"""Central config. Everything that varies lives here, read from env with working defaults.

Plan 05 Phase 4. Nothing else in the backend should call os.environ directly.

There is ONE .env, at the repo root - shared by backend, Agent, mcp, and the
data seeder. Do not add a backend/.env; four copies of a credential drift apart
and the resulting "works for me" bug costs an hour to find.
"""
import os

from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(REPO_ROOT, ".env")
load_dotenv(ENV_PATH)


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


# --- Elastic Cloud (managed; URL + API key, not cloud_id) ---
ELASTIC_URL = env("ELASTIC_URL", "")
ELASTIC_API_KEY = env("ELASTIC_API_KEY", "")
ES_INDEX = env("ES_INDEX", "secops-logs-*")

# --- MCP (contract §5: HTTP transport for a repo submission) ---
MCP_MODE = env("MCP_MODE", "http")  # http | stdio
MCP_URL = env("MCP_URL", "http://localhost:8000/mcp")

# --- Gemma (hosted via OpenRouter, per the root .env) ---
GEMMA_API_KEY = env("GEMMA_API_KEY", "")
GEMMA_MODEL = env("GEMMA_MODEL", "google/gemma-3-27b-it")
GEMMA_BASE_URL = env("GEMMA_BASE_URL", "https://openrouter.ai/api/v1")
GEMMA_LOADED = False  # flipped by agent_bridge once D's graph imports cleanly

# --- Server ---
# FLASK_PORT is the name used in the root .env; PORT overrides it for a one-off
# run. Default is 5001 because macOS AirPlay Receiver squats on 5000 and answers
# with a confusing 403 - if FLASK_PORT=5000 fails to bind, that is why.
PORT = env_int("PORT", env_int("FLASK_PORT", 5001))
HOST = env("HOST", "127.0.0.1")
DEBUG = env_bool("DEBUG", env("FLASK_ENV", "development") == "development")

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
    """Non-secret config echo for /api/health.

    Reports only whether each credential is PRESENT. Never echo the key values -
    /api/health is the one endpoint everyone screenshots during integration.
    """
    return {
        "mode": mode(),
        "env_file": ENV_PATH,
        "es_index": ES_INDEX,
        "es_configured": bool(ELASTIC_URL and ELASTIC_API_KEY),
        "gemma_configured": bool(GEMMA_API_KEY),
        "mcp_mode": MCP_MODE,
        "mcp_url": MCP_URL,
        "gemma_model": GEMMA_MODEL,
        "demo_replay": DEMO_REPLAY,
        "port": PORT,
    }
