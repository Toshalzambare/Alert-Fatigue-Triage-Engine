"""The seam between Flask and Teammate D's LangGraph agent.

Plan 05 Phase 2. This module exists so that `app.py` never imports the agent
directly and the agent never imports Flask. The entire integration surface is:

    run(question, emit, image=None, session=None) -> dict

where `emit(event: dict) -> None` takes shapes from contract §1.

Resolution order, highest priority first:
  1. DEMO_REPLAY=1        -> replay a cached real run (Phase 5 escape hatch)
  2. Agent/ importable    -> the real LangGraph graph
  3. otherwise            -> mock_agent (Phases 0-1 scripted run)

The point is that /api/ask behaves identically in all three cases. A judge
cannot tell from the wire which one is serving, because the SSE path is the
same code either way.
"""
import logging
import os
import sys

import config
import mock_agent

log = logging.getLogger("backend.agent")

_REAL_AGENT = None
_REAL_AGENT_TRIED = False


def _try_load_real_agent():
    """Import Teammate D's graph if it exists yet. Cached, including failure -
    we must not retry a heavy model import on every single request."""
    global _REAL_AGENT, _REAL_AGENT_TRIED
    if _REAL_AGENT_TRIED:
        return _REAL_AGENT
    _REAL_AGENT_TRIED = True

    agent_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Agent")
    if not os.path.isdir(agent_dir):
        return None
    if agent_dir not in sys.path:
        sys.path.insert(0, agent_dir)

    try:
        import graph  # type: ignore  # Agent/graph.py, plan 04 deliverable

        if hasattr(graph, "run"):
            _REAL_AGENT = graph
            config.GEMMA_LOADED = True
            log.info("real agent loaded from Agent/graph.py")
        else:
            log.warning("Agent/graph.py exists but has no run() - using mock")
    except Exception as exc:  # noqa: BLE001 - never let a broken agent stop boot
        log.warning("real agent not loadable (%s) - using mock", exc)
    return _REAL_AGENT


def active_backend() -> str:
    """Which implementation /api/ask will use. Surfaced by /api/health."""
    if config.DEMO_REPLAY:
        return "replay"
    return "live" if _try_load_real_agent() else "mock"


def run(question: str, emit, image: bytes | None = None, session=None) -> dict:
    """Dispatch one agent run to whichever backend is active."""
    if config.DEMO_REPLAY:
        import replay

        return replay.run(question, emit, image=image)

    agent = _try_load_real_agent()
    if agent is not None:
        return agent.run(question, emit=emit, image=image)

    return mock_agent.run(question, emit=emit, image=image)


def warm_up() -> None:
    """One throwaway load at boot so the first judge question isn't the slow
    one (plan 05 Phase 5). Load the model once at import, never per request."""
    if config.DEMO_REPLAY:
        log.info("warm-up skipped: DEMO_REPLAY is on")
        return
    agent = _try_load_real_agent()
    if agent is None:
        log.info("warm-up skipped: running on mock agent")
        return
    if hasattr(agent, "warm_up"):
        try:
            agent.warm_up()
            log.info("agent warm-up complete")
        except Exception:  # noqa: BLE001
            log.exception("agent warm-up failed (continuing anyway)")
