import threading
import uvicorn
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, Mount
import logging

from tools.impl import (
    search_logs as _search_logs,
    check_ip as _check_ip,
    get_user_activity as _get_user_activity,
    timeline_around as _timeline_around,
    validate_detection_rule as _validate_detection_rule,
)

# -----------------------------------------------------------------------------
# 1. FastMCP Registration
# -----------------------------------------------------------------------------

mcp = FastMCP(
    "secops-elastic",
    instructions="SecOps Elastic MCP server. Provides 5 security analysis tools "
                 "for querying a live Elasticsearch database of security logs. "
                 "All tools return a {data, meta} envelope."
)

@mcp.tool()
def search_logs(
    query: str,
    category: str = None,
    start: str = "now-24h",
    end: str = "now",
    limit: int = 20,
) -> dict:
    """Search security logs with natural language and optional filters.

    Use this tool to find security events matching a description. You can filter
    by event category and time range.

    Args:
        query: Natural language search (e.g. "failed logins from 45.133.1.88",
               "suspicious outbound traffic", "j.smith activity")
        category: Optional filter. One of: authentication, network, file,
                  process, dns, web, email
        start: Start time. ISO-8601 or relative like "now-24h", "now-7d"
        end: End time. ISO-8601 or "now"
        limit: Max results to return (1-50, default 20)

    Returns:
        {data: [...events], meta: {hits_total, returned, es_query, took_ms}}

    Example: search_logs("failed authentication", category="authentication",
             start="now-24h", end="now")
    """
    return _search_logs(query, category, start, end, limit)

@mcp.tool()
def check_ip(
    ip: str,
    window_hours: int = 24
) -> dict:
    """Profile an IP address's historical activity.

    Use this tool to collapse dozens of events from a single IP into one
    aggregated summary profile.

    Args:
        ip: The IPv4 address to check
        window_hours: Hours of history to analyze (default 24)

    Returns:
        {data: {total_events, countries, users_targeted...}, meta: {...}}
    """
    return _check_ip(ip, window_hours)

@mcp.tool()
def get_user_activity(
    user: str,
    start: str = "now-24h",
    end: str = "now"
) -> dict:
    """Profile a user's activity and list recent notable events.

    Use this to see if a user has logged in from multiple countries (impossible travel)
    and to see their most recent non-authentication activities.

    Args:
        user: Username (e.g., "j.smith")
        start: Start time. ISO-8601 or relative like "now-24h"
        end: End time. ISO-8601 or "now"

    Returns:
        {data: {total_events, distinct_countries, notable: [...]}, meta: {...}}
    """
    return _get_user_activity(user, start, end)

@mcp.tool()
def timeline_around(
    timestamp: str = None,
    anchor: str = None,
    minutes_before: int = 15,
    minutes_after: int = 15,
    host: str = None,
    ip: str = None
) -> dict:
    """Retrieve events immediately before and after an incident.

    Use this for time-travel investigation around a specific anchor event.

    Args:
        timestamp: The anchor timestamp (ISO-8601)
        anchor: Alias for timestamp
        minutes_before: Minutes of context before (default 15)
        minutes_after: Minutes of context after (default 15)
        host: Optional host filter
        ip: Optional IP filter

    Returns:
        {data: {before: [...], after: [...]}, meta: {...}}
    """
    return _timeline_around(timestamp, anchor, minutes_before, minutes_after, host, ip)

@mcp.tool()
def validate_detection_rule(
    query: str,
    start: str = "now-48h",
    end: str = "now"
) -> dict:
    """Test an Elasticsearch query against historical logs.

    Returns the true positive vs false positive match rates for a detection rule.

    Args:
        query: Elasticsearch DSL query string or dict
        start: Start time for evaluation window (default now-48h)
        end: End time for evaluation window

    Returns:
        {data: {matches, true_positives, false_positives, fp_rate...}, meta: {...}}
    """
    return _validate_detection_rule(query, start, end)

# -----------------------------------------------------------------------------
# 2. HTTP Bridge for Flask Backend
# -----------------------------------------------------------------------------

TOOL_MAP = {
    "search_logs": _search_logs,
    "check_ip": _check_ip,
    "get_user_activity": _get_user_activity,
    "timeline_around": _timeline_around,
    "validate_detection_rule": _validate_detection_rule,
}

async def health(request):
    return JSONResponse({"status": "ok", "server": "secops-elastic"})

async def call_tool(request):
    tool_name = request.path_params["tool_name"]
    if tool_name not in TOOL_MAP:
        return JSONResponse({"error": f"unknown tool: {tool_name}"}, status_code=404)
    
    try:
        args = await request.json()
    except Exception:
        args = {}
        
    try:
        # Logging the HTTP call to trace it easily
        logging.info(f"[HTTP] Calling tool: {tool_name} with args: {args}")
        result = TOOL_MAP[tool_name](**args)
        return JSONResponse(result)
    except Exception as e:
        logging.error(f"[HTTP] Tool {tool_name} failed: {e}")
        return JSONResponse({
            "data": [],
            "meta": {"error": str(e), "hits_total": 0, "returned": 0,
                     "truncated": False, "fields_returned": [], "es_query": {},
                     "took_ms": 0}
        }, status_code=200)

http_app = Starlette(routes=[
    Mount("/mcp", routes=[
        Route("/health", health),
        Route("/tools/{tool_name}", call_tool, methods=["POST"]),
    ])
])

def run_http():
    """Run HTTP bridge on port 8000 for Flask backend."""
    logging.info("[HTTP] Starting Starlette HTTP bridge on port 8000")
    uvicorn.run(http_app, host="127.0.0.1", port=8000, log_level="info")

if __name__ == "__main__":
    # Start HTTP bridge in background thread
    http_thread = threading.Thread(target=run_http, daemon=True)
    http_thread.start()

    # Run FastMCP stdio server
    mcp.run()
