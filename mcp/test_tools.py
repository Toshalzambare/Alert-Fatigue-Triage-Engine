import json
import pytest

from tools.impl import (
    search_logs,
    check_ip,
    get_user_activity,
    timeline_around,
    validate_detection_rule,
)

def test_search_logs_bruteforce():
    """Q1: 'What IPs seem malicious today?'"""
    result = search_logs("failed authentication", category="authentication",
                         start="2026-08-02T00:00:00Z", end="2026-08-02T23:59:59Z")
    assert result["meta"]["hits_total"] > 50
    assert "labels" not in str(result["data"])  # answer key NEVER leaks

def test_check_ip():
    """The attacker IP from Narrative 1."""
    result = check_ip("45.133.1.88", window_hours=24)
    assert result["data"]["total_events"] >= 60
    assert result["data"]["failed_logins"] >= 55
    assert result["data"]["successful_logins"] >= 1
    assert "DE" in result["data"]["countries"]

def test_get_user_activity():
    """j.smith should have brute-force + exfil events."""
    result = get_user_activity("j.smith", "2026-08-02T00:00:00Z", "2026-08-02T23:59:59Z")
    assert result["data"]["total_events"] > 0
    assert "labels" not in str(result["data"])

def test_get_user_activity_different_user():
    """john.smith is a DIFFERENT user — self-healing test."""
    result = get_user_activity("john.smith", "2026-08-02T00:00:00Z", "2026-08-02T23:59:59Z")
    assert result["data"]["total_events"] >= 3  # the 3 planted noise events
    # john.smith is NOT the attacker
    assert "process" not in result["data"].get("categories", {}) or \
           result["data"]["categories"].get("process", 0) == 0

def test_timeline_around():
    """Q3: vpn-gw-01 incident at 03:47."""
    result = timeline_around(timestamp="2026-08-02T03:47:00Z", minutes_before=15,
                             minutes_after=15, host="vpn-gw-01")
    assert len(result["data"]["before"]) >= 2
    assert len(result["data"]["after"]) >= 1
    assert "labels" not in str(result["data"])

def test_validate_detection_rule():
    """Brute-force detection rule validation."""
    query = {"query": {"bool": {"filter": [
        {"term": {"event.category": "authentication"}},
        {"term": {"event.outcome": "failure"}}
    ]}}}
    result = validate_detection_rule(query, "2026-08-02T00:00:00Z", "2026-08-02T23:59:59Z")
    assert result["data"]["matches"] > 50
    assert result["data"]["true_positives"] > 0
    assert result["data"]["false_positives"] > 0  # benign_healthcheck fires
    assert "labels" not in str(result["data"])  # labels used internally but never returned

def test_search_logs_phishing_domain():
    """Q4: phishing domain search."""
    result = search_logs("micros0ft-verify.co", start="2026-08-02T00:00:00Z",
                         end="2026-08-02T23:59:59Z")
    assert result["meta"]["hits_total"] >= 2  # r.gupta + t.nair

def test_labels_never_leak():
    """Nuclear test: grep ALL tool outputs for 'labels'."""
    tools_and_args = [
        (search_logs, {"query": "failed", "start": "now-24h", "end": "now"}),
        (check_ip, {"ip": "45.133.1.88"}),
        (get_user_activity, {"user": "j.smith", "start": "now-24h", "end": "now"}),
        (timeline_around, {"timestamp": "2026-08-02T03:47:00Z", "host": "vpn-gw-01"}),
    ]
    for fn, args in tools_and_args:
        result = fn(**args)
        serialized = json.dumps(result["data"])
        assert "labels" not in serialized, f"{fn.__name__} leaks labels!"
        assert "scenario" not in serialized, f"{fn.__name__} leaks scenario!"
        assert "is_threat" not in serialized, f"{fn.__name__} leaks is_threat!"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
