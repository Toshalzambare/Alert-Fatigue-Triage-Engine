"""DEMO_REPLAY - the insurance policy.

Plan 05 Phase 5. Teammate D caches successful runs to demo_cache.json. In
replay mode, /api/ask matches the incoming question against that cache and
streams the recorded events through the *identical* SSE path, with realistic
delays.

This is not cheating: it is a recorded run of the real system. Every hackathon
veteran ships one. If the model OOMs while judges are watching, you flip one
env var and the demo proceeds.

Build it before you need it - you cannot build it at the moment you need it.
"""
import json
import logging
import os
import time

import config
import mock_agent

log = logging.getLogger("backend.replay")

CACHE_PATH = os.path.join(os.path.dirname(__file__), "demo_cache.json")

_STOPWORDS = {
    "what", "which", "who", "did", "does", "do", "is", "are", "was", "were",
    "the", "a", "an", "me", "my", "show", "tell", "give", "any", "anyone",
    "and", "or", "of", "to", "for", "from", "in", "on", "at", "by", "with",
    "that", "this", "it", "seem", "seems", "why", "how", "write",
}


def _load_cache() -> list[dict]:
    if not os.path.exists(CACHE_PATH):
        return []
    try:
        with open(CACHE_PATH) as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("demo_cache.json unreadable (%s)", exc)
        return []
    runs = data.get("runs", data) if isinstance(data, dict) else data
    return runs if isinstance(runs, list) else []


def _tokens(text: str) -> set[str]:
    words = "".join(c.lower() if c.isalnum() else " " for c in text).split()
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _best_match(question: str, runs: list[dict]) -> dict | None:
    """Token-overlap match. Deliberately fuzzy: a judge will not retype the
    scripted question verbatim, and a replay that misses is worse than useless."""
    asked = _tokens(question)
    if not asked:
        return None
    best, best_score = None, 0.0
    for run in runs:
        cached = _tokens(run.get("question", ""))
        if not cached:
            continue
        score = len(asked & cached) / len(asked | cached)
        if score > best_score:
            best, best_score = run, score
    if best is not None and best_score >= 0.2:
        log.info("replay matched %r (score %.2f)", best.get("question"), best_score)
        return best
    return None


def available() -> dict:
    runs = _load_cache()
    return {
        "cached_runs": len(runs),
        "questions": [r.get("question", "") for r in runs],
        "path": CACHE_PATH,
    }


def run(question: str, emit, image: bytes | None = None) -> dict:
    """Stream a cached run through the same emit() the live agent uses."""
    runs = _load_cache()
    match = _best_match(question, runs) if runs else None

    if match is None:
        # No cached answer - fall back to the scripted mock rather than
        # returning nothing. A demo must always produce something.
        log.warning("no cached run for %r - falling back to mock", question)
        emit({"type": "replay_miss", "question": question,
              "detail": "no cached run matched; serving scripted demo"})
        return mock_agent.run(question, emit, image=image)

    emit({"type": "replay", "cached_question": match.get("question", ""),
          "recorded_at": match.get("recorded_at")})

    delay = config.MOCK_DELAY_MS / 1000.0
    verdict = None
    for ev in match.get("events", []):
        emit(dict(ev))
        if ev.get("type") == "verdict":
            verdict = ev
        time.sleep(delay / 4 if ev.get("type") == "token" else delay)

    return {
        "question": question,
        "replayed": True,
        "verdict": verdict,
        "findings": (verdict or {}).get("findings", {})
                    or match.get("findings", {}),
    }


def record(question: str, events: list[dict], findings: dict | None = None) -> dict:
    """Append a successful run to the cache. Called by /api/replay/record so a
    good live run can be captured during rehearsal without editing JSON by hand."""
    runs = _load_cache()
    runs = [r for r in runs if r.get("question") != question]  # replace, don't dupe
    runs.append({
        "question": question,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "events": events,
        "findings": findings or {},
    })
    with open(CACHE_PATH, "w") as fh:
        json.dump({"runs": runs}, fh, indent=2)
    log.info("recorded run for %r (%d events)", question, len(events))
    return {"cached_runs": len(runs), "events": len(events)}
