"""Thin client for Teammate C's FastMCP server.

Plan 05 Phase 3. Flask needs this for exactly one reason: `/api/timeline`
bypasses the LLM entirely and calls `timeline_around()` directly, because it
backs a button a judge clicks and must be fast (~200ms) and unbreakable.

Everything else goes through the agent, which has its own MCP client.

Until C's server is up, `call()` returns contract-shaped stub data so the
frontend's Timeline view can be built and demoed today.
"""
import logging
import time

import config

log = logging.getLogger("backend.mcp")

_TIMEOUT_S = 10


def available() -> bool:
    """Is C's server reachable? Used by /api/health, never cached - a probe
    that lies about current state is worse than no probe."""
    if config.MCP_MODE != "http":
        return False
    try:
        import requests

        r = requests.get(config.MCP_URL.rstrip("/") + "/health", timeout=2)
        return r.status_code < 500
    except Exception:  # noqa: BLE001
        return False


def call(tool: str, args: dict) -> dict:
    """Invoke one MCP tool. Never raises into the caller.

    Contract §4 / plan 03 Phase 3 rule 1: any exception becomes an empty,
    correctly-shaped result. An MCP exception can kill a graph mid-demo; an
    empty result triggers self-healing and looks intentional.
    """
    started = time.time()
    try:
        import requests

        r = requests.post(
            config.MCP_URL.rstrip("/") + f"/tools/{tool}",
            json=args,
            timeout=_TIMEOUT_S,
        )
        r.raise_for_status()
        payload = r.json()
        log.info("mcp %s ok in %dms", tool, (time.time() - started) * 1000)
        return payload
    except Exception as exc:  # noqa: BLE001
        log.warning("mcp %s unavailable (%s) - serving stub", tool, exc)
        return _stub(tool, args, error=str(exc))


# --------------------------------------------------------------- stubs ---
def _envelope(data, *, hits_total, returned, es_query, took_ms, error=None,
              fields=None, truncated=False, extra_meta=None) -> dict:
    """Contract §3 envelope. Every tool return carries this shape."""
    meta = {
        "hits_total": hits_total,
        "returned": returned,
        "truncated": truncated,
        "fields_returned": fields or [],
        "es_query": es_query,
        "took_ms": took_ms,
        "stub": True,
    }
    if error:
        meta["error"] = error
    if extra_meta:
        meta.update(extra_meta)
    return {"data": data, "meta": meta}


def _stub(tool: str, args: dict, error: str | None = None) -> dict:
    """Contract-shaped fake responses drawn from plan 02's SCENARIOS values."""
    if tool == "timeline_around":
        return _stub_timeline(args, error)
    if tool == "validate_detection_rule":
        return _envelope(
            {"matches": 61, "true_positives": 60, "false_positives": 1,
             "fp_rate": 0.016,
             "sample_fps": [{"@timestamp": "2026-08-02T02:14:00Z",
                             "source.ip": "10.0.4.99",
                             "message": "health-check auth failure"}]},
            hits_total=61, returned=61, took_ms=48,
            fields=["event.category", "event.outcome", "source.ip"],
            es_query={"query": {"bool": {"filter": [
                {"term": {"event.category": "authentication"}},
                {"term": {"event.outcome": "failure"}}]}}},
            error=error,
        )
    return _envelope([], hits_total=0, returned=0, took_ms=1,
                     es_query={}, error=error or f"no stub for tool {tool!r}")


def _stub_timeline(args: dict, error: str | None) -> dict:
    """Narrative 3 from plan 02 - the vpn-gw-01 incident at 03:47Z.

    Quiet before, loud after. That asymmetry is the entire visual payoff of
    the time-travel feature, so the stub has to preserve it.
    """
    anchor = args.get("anchor") or args.get("timestamp") or "2026-08-02T03:47:00Z"
    host = args.get("host") or "vpn-gw-01"
    return _envelope(
        {
            "anchor": anchor,
            "host": host,
            "before": [
                {"@timestamp": "2026-08-02T03:35:00Z", "event.category": "process",
                 "event.action": "process_started", "process.name": "cron",
                 "host.name": host, "phase": "before",
                 "message": "CRON[2841]: (root) CMD (/usr/bin/backup.sh)"},
                {"@timestamp": "2026-08-02T03:41:00Z", "event.category": "authentication",
                 "event.action": "login_success", "user.name": "svc.monitor",
                 "host.name": host, "phase": "before",
                 "message": "Accepted publickey for svc.monitor"},
                {"@timestamp": "2026-08-02T03:43:00Z", "event.category": "file",
                 "event.action": "file_created", "host.name": host, "phase": "before",
                 "message": "created /tmp/.hidden/update.sh"},
            ],
            "after": [
                {"@timestamp": "2026-08-02T03:47:00Z", "event.category": "process",
                 "event.action": "process_started", "process.name": "nc",
                 "host.name": host, "phase": "after",
                 "message": "nc -lvp 4444"},
                {"@timestamp": "2026-08-02T03:50:00Z", "event.category": "network",
                 "event.action": "listening_port_opened", "host.name": host,
                 "phase": "after", "message": "port 4444 listening"},
                {"@timestamp": "2026-08-02T03:56:00Z", "event.category": "network",
                 "event.action": "connection", "network.direction": "outbound",
                 "network.bytes": 4200000, "source.ip": "45.133.1.88",
                 "host.name": host, "phase": "after",
                 "message": "outbound 4.2MB -> 45.133.1.88"},
            ],
            "summary": {
                "before_count": 3,
                "after_count": 3,
                "new_categories_after": ["network"],
            },
        },
        hits_total=6, returned=6, took_ms=27,
        fields=["@timestamp", "event.category", "event.action", "process.name",
                "network.bytes", "host.name", "message"],
        es_query={"query": {"bool": {"filter": [
            {"term": {"host.name": host}},
            {"range": {"@timestamp": {"gte": "2026-08-02T03:32:00Z",
                                      "lte": "2026-08-02T04:02:00Z"}}}]}}},
        error=error,
    )
