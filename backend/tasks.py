"""Celery tasks. This is where the agent actually runs.

Everything here executes in a worker process, never in the web process. The
only channel back to Flask is `celery_app.publish()`, which writes to Redis.
"""
import logging
import sys
import time

import config
import llm
from celery_app import celery_app, publish, set_state

log = logging.getLogger("backend.tasks")

_agent = None


def _load_agent():
    """Import Teammate D's LangGraph module once per worker process.

    Agent/graph.py imports its siblings as top-level modules (`from prompts
    import ...`), so the Agent directory itself has to be on sys.path - importing
    it as a package would break those imports.
    """
    global _agent
    if _agent is not None:
        return _agent

    if config.AGENT_DIR not in sys.path:
        sys.path.insert(0, config.AGENT_DIR)

    llm.apply_env()  # agent reads GEMMA_* / MCP_URL from os.environ
    import graph  # noqa: PLC0415  - deliberately deferred to worker startup

    _agent = graph
    log.info("agent loaded from %s", config.AGENT_DIR)
    return _agent


def _emitter(job_id: str):
    """Build the emit() callback handed to the agent.

    One function, one dict argument - the same contract the agent already
    expects. It has no idea Redis is involved.
    """

    def emit(event: dict) -> None:
        event.setdefault("ts", time.time())
        publish(job_id, event)

    return emit


@celery_app.task(name="sentinel.run_agent", bind=True)
def run_agent(self, job_id: str, question: str, image_b64: str | None = None):
    """Run one investigation end to end.

    Always publishes a terminal event. A worker that dies without one would
    leave the browser's SSE connection open until it times out.
    """
    emit = _emitter(job_id)
    set_state(job_id, status="running", question=question, task_id=self.request.id)

    image = None
    if image_b64:
        import base64

        try:
            image = base64.b64decode(image_b64)
        except Exception:  # noqa: BLE001
            emit({"type": "error", "message": "could not decode uploaded image"})

    try:
        agent = _load_agent()
        result = agent.run(question, emit=emit, image=image)

        set_state(
            job_id,
            status="done",
            result=result,
            findings=result.get("findings", {}),
            verdict=result.get("verdict"),
        )
        emit({"type": "done", "job_id": job_id})
        return {"job_id": job_id, "status": "done"}

    except Exception as exc:  # noqa: BLE001 - a demo must never surface a traceback
        log.exception("agent failed job=%s", job_id)
        set_state(job_id, status="error", error=str(exc))
        emit({"type": "error", "message": str(exc)})
        return {"job_id": job_id, "status": "error", "error": str(exc)}

    finally:
        # Sentinel closes the SSE stream. It must be published on every path,
        # including a soft time limit killing the task mid-run.
        emit({"type": "eof"})


@celery_app.task(name="sentinel.forge_sigma", bind=True)
def forge_sigma(self, job_id: str, findings: dict, start: str, end: str):
    """Draft a detection rule, convert it deterministically, then validate it."""
    import sigma

    emit = _emitter(job_id)
    set_state(job_id, status="running", task_id=self.request.id)

    try:
        emit({"type": "sigma_drafting", "findings": findings})
        result = sigma.forge(findings, start=start, end=end)
        emit({
            "type": "sigma_rule",
            "yaml": result["yaml"],
            "es_query": result["es_query"],
        })
        emit({
            "type": "sigma_validation",
            "validation": result["validation"],
            "headline": result["headline"],
        })
        set_state(job_id, status="done", result=result)
        emit({"type": "done", "job_id": job_id})
        return {"job_id": job_id, "status": "done"}

    except Exception as exc:  # noqa: BLE001
        log.exception("sigma forge failed job=%s", job_id)
        set_state(job_id, status="error", error=str(exc))
        emit({"type": "error", "message": str(exc)})
        return {"job_id": job_id, "status": "error"}

    finally:
        emit({"type": "eof"})


@celery_app.task(name="sentinel.warm_up")
def warm_up():
    """Fire one throwaway load at worker start so the first judge question is
    not the slow one."""
    try:
        agent = _load_agent()
        if hasattr(agent, "warm_up"):
            agent.warm_up()
        return {"warmed": True, "provider": llm.active_provider()}
    except Exception as exc:  # noqa: BLE001
        log.warning("warm-up failed (continuing): %s", exc)
        return {"warmed": False, "error": str(exc)}
