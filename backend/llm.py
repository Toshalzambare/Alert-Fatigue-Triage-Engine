"""LLM provider resolution and health, with a local fallback.

Order of preference:
  1. Hosted (OpenRouter) - GEMMA_API_KEY is set. This is the normal path.
  2. Local (Ollama / llama.cpp / any OpenAI-compatible server) - used when the
     hosted call fails or no key is configured.

No local model is installed today, so the fallback is wired but inert: probing
it is cheap and never blocks a request. The moment `ollama serve` is running
with a gemma tag pulled, it becomes a live safety net with no code change.

The agent (Agent/gemma_client.py) builds its own client and owns inference.
This module owns *policy*: which provider should be used, and is it reachable.
"""
import logging
import os

import config

log = logging.getLogger("backend.llm")


def _probe(base_url: str, timeout: float = 1.5) -> bool:
    """Is an OpenAI-compatible server answering here?"""
    try:
        import requests

        # Ollama serves /api/tags; llama.cpp and vLLM serve /v1/models.
        root = base_url.rstrip("/").removesuffix("/v1")
        for path in ("/api/tags", "/v1/models"):
            try:
                r = requests.get(root + path, timeout=timeout)
                if r.status_code < 500:
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False
    except Exception:  # noqa: BLE001
        return False


def local_available() -> bool:
    return _probe(config.GEMMA_LOCAL_URL)


def hosted_configured() -> bool:
    return bool(config.GEMMA_API_KEY)


def active_provider() -> str:
    """Which provider a run would use right now."""
    if hosted_configured():
        return "hosted"
    if local_available():
        return "local"
    return "none"


def apply_env() -> None:
    """Export the settings Agent/gemma_client.py reads from os.environ.

    The agent module was written to read GEMMA_API_KEY / GEMMA_LOCAL_URL
    directly. Rather than rewrite it, the backend loads the single root .env and
    republishes those values into the process the worker runs in. One source of
    truth, no duplicated dotenv loading.
    """
    if config.GEMMA_API_KEY:
        os.environ["GEMMA_API_KEY"] = config.GEMMA_API_KEY
    os.environ["GEMMA_LOCAL_URL"] = config.GEMMA_LOCAL_URL
    os.environ["GEMMA_MODEL"] = config.GEMMA_MODEL
    os.environ["GEMMA_LOCAL_MODEL"] = config.GEMMA_LOCAL_MODEL
    if config.ELASTIC_URL:
        os.environ["ELASTIC_URL"] = config.ELASTIC_URL
    if config.ELASTIC_API_KEY:
        os.environ["ELASTIC_API_KEY"] = config.ELASTIC_API_KEY
    os.environ["ES_INDEX"] = config.ES_INDEX
    os.environ["MCP_URL"] = config.MCP_URL


def status() -> dict:
    """For /api/health. Reports presence and reachability, never key values."""
    hosted = hosted_configured()
    local = local_available()
    provider = "hosted" if hosted else ("local" if local else "none")
    return {
        "status": "ok" if provider != "none" else "unavailable",
        "provider": provider,
        "hosted": {
            "configured": hosted,
            "model": config.GEMMA_MODEL,
            "base_url": config.GEMMA_BASE_URL,
        },
        "local_fallback": {
            "reachable": local,
            "model": config.GEMMA_LOCAL_MODEL,
            "base_url": config.GEMMA_LOCAL_URL,
            "detail": None if local else "no local model running (optional)",
        },
    }
