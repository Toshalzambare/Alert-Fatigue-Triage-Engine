"""Fake agent runs, replayed through the real SSE path.

Plan 05 Phase 1: "Build the entire streaming path before the agent exists."
This is the backend's stub-first equivalent of C's tool stubs - it unblocks the
frontend for a full hour without waiting on Teammate D.

Event shapes follow contract §1 (plans/01_FRONTEND.md). The scripted run below
is Narrative 1 from plans/02_ELASTIC_MOCK_DATA.md: brute force -> success ->
exfil, which is demo question 1 and must be flawless.

When D's real graph lands, app.run_agent() swaps this for the real call and
nothing else in the backend changes.
"""
import json
import os
import time

import config

# --- Narrative 1: 45.133.1.88 brute-forces j.smith, succeeds, exfiltrates ---
# Literal values match plans/02_ELASTIC_MOCK_DATA.md so the frontend renders
# the same strings the real pipeline will produce.
BRUTE_FORCE_RUN = [
    {"type": "triage", "intent": "threat_hunt", "entities": {"time": "today"}},
    {
        "type": "tool_call",
        "tool": "search_logs",
        "hop": 1,
        "args": {
            "query": "failed authentication",
            "category": "authentication",
            "start": "now-24h",
            "end": "now",
            "limit": 20,
        },
    },
    {
        "type": "tool_result",
        "tool": "search_logs",
        "hop": 1,
        "meta": {
            "hits_total": 1284,
            "returned": 20,
            "truncated": True,
            "fields_returned": [
                "@timestamp", "event.category", "event.action", "event.outcome",
                "source.ip", "source.geo.country", "user.name", "host.name",
                "url.domain", "network.bytes", "process.name", "message",
            ],
            "es_query": {
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"event.category": "authentication"}},
                            {"term": {"event.outcome": "failure"}},
                            {"range": {"@timestamp": {"gte": "now-24h", "lte": "now"}}},
                        ]
                    }
                },
                "size": 20,
            },
            "took_ms": 34,
        },
    },
    {
        "type": "agent_hop",
        "from": "search_logs",
        "to": "check_ip",
        "reason": "IP 45.133.1.88 had 60 failures",
    },
    {
        "type": "tool_call",
        "tool": "check_ip",
        "hop": 2,
        "args": {"ip": "45.133.1.88", "window_hours": 24},
    },
    {
        "type": "tool_result",
        "tool": "check_ip",
        "hop": 2,
        "data": {
            "ip": "45.133.1.88",
            "total_events": 64,
            "first_seen": "2026-08-02T14:02:11Z",
            "last_seen": "2026-08-02T14:31:02Z",
            "countries": ["DE"],
            "users_targeted": ["j.smith"],
            "categories": {"authentication": 61, "network": 3},
            "failed_logins": 60,
            "successful_logins": 1,
        },
        "meta": {
            "hits_total": 64,
            "returned": 64,
            "raw_documents": 0,  # pure aggregation - the efficiency claim
            "truncated": False,
            "fields_returned": ["source.ip", "user.name", "event.action"],
            "es_query": {
                "query": {"bool": {"filter": [{"term": {"source.ip": "45.133.1.88"}}]}},
                "size": 0,
                "aggs": {
                    "by_outcome": {"terms": {"field": "event.outcome"}},
                    "by_user": {"terms": {"field": "user.name"}},
                },
            },
            "took_ms": 12,
        },
    },
    {
        "type": "agent_hop",
        "from": "check_ip",
        "to": "get_user_activity",
        "reason": "60 failures then 1 success at 14:21 - j.smith is compromised",
    },
    # Self-healing fires here: j.smith misses, john.smith hits.
    {
        "type": "tool_call",
        "tool": "get_user_activity",
        "hop": 3,
        "args": {"user": "j.smith", "start": "now-24h", "end": "now"},
    },
    {
        "type": "tool_result",
        "tool": "get_user_activity",
        "hop": 3,
        "meta": {"hits_total": 0, "returned": 0, "took_ms": 8, "es_query": {}},
    },
    {
        "type": "healing",
        "attempt": 1,
        "fix": "username_format",
        "from": "j.smith",
        "to": "john.smith",
    },
    {
        "type": "tool_result",
        "tool": "get_user_activity",
        "hop": 3,
        "healing": True,
        "data": {
            "user": "john.smith",
            "distinct_countries": ["DE"],
            "categories": {"authentication": 61, "process": 1, "network": 3},
            "notable": [
                {"@timestamp": "2026-08-02T14:26:00Z", "process.name": "powershell.exe",
                 "host.name": "vpn-gw-01"},
                {"@timestamp": "2026-08-02T14:31:00Z", "network.bytes": 4200000,
                 "network.direction": "outbound"},
            ],
        },
        "meta": {
            "hits_total": 47,
            "returned": 47,
            "truncated": False,
            "fields_returned": ["@timestamp", "user.name", "event.category",
                                "process.name", "network.bytes", "host.name"],
            "es_query": {
                "query": {"bool": {"filter": [{"term": {"user.name": "john.smith"}}]}}
            },
            "took_ms": 21,
        },
    },
    {
        "type": "injection",
        "neutralized": True,
        "pattern": "ignore previous instructions",
    },
    # A few tokens so the frontend can prove incremental text rendering.
    {"type": "token", "text": "Confirmed compromise. "},
    {"type": "token", "text": "45.133.1.88 (DE) brute-forced john.smith "},
    {"type": "token", "text": "across 60 attempts, succeeded at 14:21, "},
    {"type": "token", "text": "then exfiltrated 4.2 MB outbound."},
    {
        "type": "verdict",
        "severity": "high",
        "summary": (
            "45.133.1.88 conducted a successful brute-force against john.smith on "
            "vpn-gw-01 (60 failures, 1 success at 14:21), followed by powershell.exe "
            "execution and 4.2 MB of outbound transfer. This is a compromise with "
            "data exfiltration, not a failed login burst."
        ),
        "iocs": ["45.133.1.88", "john.smith", "vpn-gw-01", "powershell.exe"],
        "findings": {
            "ips_of_interest": ["45.133.1.88"],
            "users": ["john.smith"],
            "hosts": ["vpn-gw-01"],
            "anchor_timestamp": "2026-08-02T14:26:00Z",
        },
    },
]


def _load_from_file() -> list | None:
    """Prefer mock_events.jsonl if the frontend has authored one (contract §1
    says Teammate A owns that file). Falls back to the scripted run."""
    path = config.MOCK_EVENTS
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(__file__), path)
    if not os.path.exists(path):
        return None
    events = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a malformed line must never kill a demo
    return events or None


def run(question: str, emit, image: bytes | None = None) -> dict:
    """Same signature the real agent will expose: (question, emit) -> result.

    Paced with a delay so the frontend's hop cards appear in sequence - batch
    rendering at the end defeats the entire purpose of the trace pane.
    """
    events = _load_from_file() or BRUTE_FORCE_RUN
    delay = config.MOCK_DELAY_MS / 1000.0

    if image:
        emit({
            "type": "vision",
            "brand_impersonated": "Microsoft 365",
            "extracted_domain": "micros0ft-verify.co",
            "typosquat": True,
            "red_flags": ["urgency banner", "mismatched sender"],
        })
        time.sleep(delay)

    verdict = None
    for ev in events:
        emit(dict(ev))
        if ev.get("type") == "verdict":
            verdict = ev
        # Tokens stream faster than tool cards - they're words, not steps.
        time.sleep(delay / 4 if ev.get("type") == "token" else delay)

    return {
        "question": question,
        "verdict": verdict,
        "findings": (verdict or {}).get("findings", {}),
    }
