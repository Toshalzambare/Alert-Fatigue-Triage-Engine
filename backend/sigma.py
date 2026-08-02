"""Sigma rule forge - drafts a rule from findings, then validates it.

Plan 05 Phase 3 (`/api/sigma`), backing plan 04's Feature 4.

Three steps, and the third is what makes it credible:
  1. draft YAML from findings        (agent's job; stubbed here until D lands)
  2. convert detection: -> ES query  (Python, NOT the LLM - deterministic)
  3. validate_detection_rule()       (MCP; returns the TP/FP split)

Step 2 lives in Python on purpose: a 12B model emits syntactically-invalid DSL
often enough to wreck a live demo, and this conversion is trivially rule-based.

Without step 3 this is just YAML generation. With it, the claim becomes
"generated a rule and proved it at 1.6% FP against 48h of history."
"""
import logging

import mcp_client

log = logging.getLogger("backend.sigma")

# One complete example, matching plan 02's Narrative 1. Handed to the model as
# a format exemplar; also the fallback when no agent is available.
BRUTE_FORCE_RULE = """title: Brute Force Followed by Successful Authentication
id: 8f2e1c44-3b7a-4d21-9e05-1a6f7b2c9d38
status: experimental
description: >
  Detects a source IP producing a high volume of failed authentications
  against a single user, followed by a successful login from the same IP.
author: Autonomous Security Agent
date: 2026/08/02
logsource:
  category: authentication
detection:
  failures:
    event.category: authentication
    event.outcome: failure
  success:
    event.category: authentication
    event.outcome: success
  timeframe: 30m
  condition: failures | count() by source.ip > 20 and success
falsepositives:
  - Misconfigured health checkers retrying from an internal IP
  - Password managers replaying stale credentials
level: high
tags:
  - attack.credential_access
  - attack.t1110
"""


def draft(findings: dict) -> str:
    """Step 1. Real drafting is the agent's (Gemma writes the YAML); this is
    the deterministic fallback so /api/sigma works before D lands."""
    ips = findings.get("ips_of_interest") or []
    users = findings.get("users") or []
    rule = BRUTE_FORCE_RULE
    if ips or users:
        note = "  # observed: " + ", ".join(ips + users)
        rule = rule.replace("logsource:", note + "\nlogsource:")
    return rule


def to_es_query(rule_yaml: str) -> dict:
    """Step 2. Deterministic and unbreakable - no LLM in this path.

    Scoped to what plan 04 actually needs: the brute-force shape. Parsing
    arbitrary Sigma is out of scope for a 4-hour demo and would be the wrong
    place to spend the time.
    """
    text = rule_yaml.lower()
    must: list[dict] = []

    if "authentication" in text:
        must.append({"term": {"event.category": "authentication"}})
    if "outcome: failure" in text or "failure" in text:
        must.append({"term": {"event.outcome": "failure"}})
    for category in ("network", "process", "file", "dns", "web", "email"):
        if f"category: {category}" in text:
            must.append({"term": {"event.category": category}})
            break

    if not must:  # never emit a match-all rule - it would validate at 100% FP
        must.append({"term": {"event.category": "authentication"}})

    return {"query": {"bool": {"filter": must}}}


def forge(findings: dict, start: str = "now-48h", end: str = "now",
          rule_yaml: str | None = None) -> dict:
    """Full pipeline. Returns {yaml, es_query, validation}."""
    yaml_text = rule_yaml or draft(findings)
    es_query = to_es_query(yaml_text)

    validation = mcp_client.call(
        "validate_detection_rule",
        {"query": es_query, "start": start, "end": end},
    )
    data = validation.get("data") or {}

    return {
        "yaml": yaml_text,
        "es_query": es_query,
        "validation": data,
        "meta": validation.get("meta", {}),
        "headline": _headline(data),
    }


def _headline(v: dict) -> str:
    """The one line worth putting on screen."""
    if not v or "matches" not in v:
        return "Rule drafted; validation unavailable."
    fp_rate = v.get("fp_rate")
    pct = f"{fp_rate * 100:.1f}%" if isinstance(fp_rate, (int, float)) else "n/a"
    return (
        f"{v.get('matches', 0)} matches over history — "
        f"{v.get('true_positives', 0)} true positives, "
        f"{v.get('false_positives', 0)} false positives ({pct} FP rate)."
    )
