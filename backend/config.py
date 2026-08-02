"""Central config. Everything that varies lives here, read from env with
working defaults.

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


# --- Sibling services ---
AGENT_DIR = os.path.join(REPO_ROOT, "Agent")
MCP_DIR = os.path.join(REPO_ROOT, "mcp")

# --- Elastic Cloud (queried by MCP, never by Flask) ---
ELASTIC_URL = env("ELASTIC_URL", "")
ELASTIC_API_KEY = env("ELASTIC_API_KEY", "")
ES_INDEX = env("ES_INDEX", "secops-logs-*")

# --- MCP (contract §5: HTTP transport) ---
MCP_URL = env("MCP_URL", "http://127.0.0.1:8000/mcp")

# --- Gemma: hosted primary, local fallback ---
GEMMA_API_KEY = env("GEMMA_API_KEY", "")
GEMMA_MODEL = env("GEMMA_MODEL", "google/gemma-4-26b-a4b-it:free")
GEMMA_BASE_URL = env("GEMMA_BASE_URL", "https://openrouter.ai/api/v1")
# Fallback target. Wired but inert until something is serving here - typically
# `ollama serve` with a gemma tag pulled.
GEMMA_LOCAL_URL = env("GEMMA_LOCAL_URL", "http://127.0.0.1:11434/v1")
GEMMA_LOCAL_MODEL = env("GEMMA_LOCAL_MODEL", "gemma3:12b")

# --- Celery / Redis ---
REDIS_URL = env("REDIS_URL", "redis://127.0.0.1:6379/0")
TASK_SOFT_LIMIT_S = env_int("TASK_SOFT_LIMIT_S", 240)
TASK_HARD_LIMIT_S = env_int("TASK_HARD_LIMIT_S", 300)
JOB_TTL_S = env_int("JOB_TTL_S", 3600)  # how long job events survive in Redis

# --- Server ---
# FLASK_PORT is the name used in the root .env; PORT overrides for a one-off run.
PORT = env_int("PORT", env_int("FLASK_PORT", 5000))
HOST = env("HOST", "127.0.0.1")
DEBUG = env_bool("DEBUG", env("FLASK_ENV", "development") == "development")
CORS_ORIGINS = env("CORS_ORIGINS", "*")

# --- Streaming ---
STREAM_TIMEOUT_S = env_int("STREAM_TIMEOUT_S", 300)  # never block unbounded
HEARTBEAT_S = env_int("HEARTBEAT_S", 15)  # SSE keepalive interval

# --- Uploads ---
MAX_UPLOAD_MB = env_int("MAX_UPLOAD_MB", 10)


def summary() -> dict:
    """Non-secret config echo for /api/health.

    Reports only whether each credential is PRESENT. Never echo key values -
    /api/health is the one endpoint everyone screenshots during integration.
    """
    return {
        "env_file": ENV_PATH,
        "es_index": ES_INDEX,
        "es_configured": bool(ELASTIC_URL and ELASTIC_API_KEY),
        "gemma_configured": bool(GEMMA_API_KEY),
        "gemma_model": GEMMA_MODEL,
        "mcp_url": MCP_URL,
        "redis_url": REDIS_URL,
        "port": PORT,
    }
