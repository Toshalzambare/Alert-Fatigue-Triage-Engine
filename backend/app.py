"""Flask service layer - transport, session, orchestration. No business logic.

Plan 05, all phases:
  Phase 0  /api/health                  the integration dashboard
  Phase 1  /api/ask + /api/stream       the streaming path
  Phase 2  agent_bridge                 D's graph behind one function
  Phase 3  /api/upload /timeline /sigma the remaining routes
  Phase 4  config.py + run.sh           one-command startup
  Phase 5  DEMO_REPLAY + warm-up        demo-day hardening

Every reasoning decision belongs to Teammate D, every query to Teammate C. If
there's an ES query or a prompt in this file, it's in the wrong plan.
"""
import base64
import io
import json
import logging
import queue
import threading
import time

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

import agent_bridge
import config
import mcp_client
import replay
import sigma
from session import SENTINEL, STORE

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("backend")
# urllib3 logs a line per MCP probe; at DEBUG that buries our own output.
logging.getLogger("urllib3").setLevel(logging.WARNING)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024

# Vite dev server is a different origin; the browser needs CORS to reach us.
CORS(app, resources={r"/api/*": {"origins": config.CORS_ORIGINS}})

BOOT_TIME = time.time()


# ---------------------------------------------------------------- probes ---
def probe_es() -> dict:
    """Teammate B's Elastic Cloud. Credentials come from the root .env."""
    if not (config.ELASTIC_URL and config.ELASTIC_API_KEY):
        return {"status": "not_configured",
                "detail": f"ELASTIC_URL / ELASTIC_API_KEY unset in {config.ENV_PATH}"}
    host = config.ELASTIC_URL.split("//")[-1].split(":")[0]
    return {"status": "configured", "index": config.ES_INDEX, "host": host,
            "detail": "credentials present; queries go through MCP, not Flask"}


def probe_mcp() -> dict:
    """Teammate C's FastMCP server."""
    reachable = mcp_client.available()
    return {
        "status": "ok" if reachable else "stub",
        "mode": config.MCP_MODE,
        "url": config.MCP_URL,
        "detail": None if reachable else "serving contract-shaped stub data",
    }


def probe_agent() -> dict:
    """Teammate D's graph. Gemma is hosted (OpenRouter), so "configured" means
    an API key is present rather than a model being resident in VRAM."""
    backend = agent_bridge.active_backend()
    return {
        "status": "ok" if backend == "live" else backend,
        "backend": backend,
        "model": config.GEMMA_MODEL,
        "api_key_present": bool(config.GEMMA_API_KEY),
    }


# ---------------------------------------------------------------- health ---
@app.get("/api/health")
def health():
    """The integration dashboard. When someone says "it's broken", this says
    which of the four subsystems is actually down, in one second, instead of
    four people guessing."""
    subsystems = {
        "elastic": probe_es(),
        "mcp": probe_mcp(),
        "agent": probe_agent(),
        "backend": {"status": "ok"},
    }
    degraded = [k for k, v in subsystems.items() if v["status"] not in ("ok", "configured")]
    return jsonify({
        "ok": True,
        "ready": not degraded,
        "degraded": degraded,
        "uptime_s": round(time.time() - BOOT_TIME, 1),
        "subsystems": subsystems,
        "config": config.summary(),
        "replay": replay.available() if config.DEMO_REPLAY else {"enabled": False},
        "jobs": STORE.job_count(),
        "sessions": STORE.session_count(),
    })


# ------------------------------------------------------------ agent runner ---
def run_agent(job_id: str, payload: dict) -> None:
    """Worker thread body. Wrapped in try/except with SENTINEL in finally -
    an unhandled exception here is invisible in Flask's console and looks
    exactly like a hung UI. Plan 05 calls this the #1 way a live demo dies."""
    job = STORE.get_job(job_id)
    if job is None:
        return

    try:
        result = agent_bridge.run(
            payload.get("question", ""),
            emit=job.emit,
            image=payload.get("image"),
        )
        job.result = result
        job.status = "done"

        # Carry findings onto the session so /api/timeline and /api/sigma know
        # what we just found, without an NL round-trip.
        sess = STORE.get_session(job.session_id)
        if result.get("findings"):
            sess.findings = result["findings"]
        if result.get("verdict"):
            sess.last_verdict = result["verdict"]
        sess.tool_calls.extend(
            e for e in job.events if e.get("type") in ("tool_call", "tool_result")
        )
        job.emit({"type": "done", "job_id": job_id})
    except Exception as exc:  # noqa: BLE001 - a demo must never surface a traceback
        job.status = "error"
        job.error = str(exc)
        log.exception("agent failed job=%s", job_id)
        job.emit({"type": "error", "message": str(exc)})
    finally:
        job.close()


def _start_job(payload: dict, question: str):
    sess = STORE.get_session(payload.get("session_id"))
    job = STORE.create_job(sess.id, question)
    threading.Thread(
        target=run_agent, args=(job.id, payload), daemon=True,
        name=f"agent-{job.id[:8]}",
    ).start()
    log.info("job %s started: %r", job.id[:8], question[:60])
    return job, sess


@app.post("/api/ask")
def ask():
    """Start an agent run. Returns immediately with a job_id; the caller then
    opens /api/stream/<job_id> to watch it."""
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400

    job, sess = _start_job(payload, question)
    return jsonify({"job_id": job.id, "session_id": sess.id, "status": "running"})


# ---------------------------------------------------------------- upload ---
@app.post("/api/upload")
def upload():
    """Multimodal entry point. Accepts multipart or base64 JSON, validates the
    bytes are a real image, then reuses the identical job/queue path as /api/ask.

    Deliberately not a second streaming mechanism - one path, one set of bugs.
    """
    question = ""
    raw: bytes | None = None

    if "image" in request.files:
        fh = request.files["image"]
        raw = fh.read()
        question = (request.form.get("question") or "").strip()
        session_id = request.form.get("session_id")
    else:
        payload = request.get_json(silent=True) or {}
        b64 = payload.get("image_base64") or ""
        question = (payload.get("question") or "").strip()
        session_id = payload.get("session_id")
        if b64:
            if "," in b64[:64]:  # tolerate a data: URL prefix
                b64 = b64.split(",", 1)[1]
            try:
                raw = base64.b64decode(b64, validate=True)
            except Exception:  # noqa: BLE001
                return jsonify({"error": "image_base64 is not valid base64"}), 400

    if not raw:
        return jsonify({"error": "no image provided (multipart 'image' or 'image_base64')"}), 400

    # Validate it's genuinely an image - a corrupt upload should fail here with
    # a clear message, not deep inside the vision model mid-demo.
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        img.verify()
        fmt, size = img.format, img.size
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "not a valid image", "detail": str(exc)}), 400

    question = question or "Did anyone click this?"
    job, sess = _start_job(
        {"question": question, "image": raw, "session_id": session_id}, question
    )
    return jsonify({
        "job_id": job.id, "session_id": sess.id, "status": "running",
        "image": {"format": fmt, "width": size[0], "height": size[1],
                  "bytes": len(raw)},
    })


# -------------------------------------------------------------- timeline ---
@app.post("/api/timeline")
def timeline():
    """The *Inspect Timeline* button. Bypasses the LLM entirely - calls C's
    timeline_around() directly and returns JSON. No agent, no streaming, ~200ms.

    Fast and unbreakable is exactly what you want behind a button a judge clicks.
    """
    payload = request.get_json(silent=True) or {}
    sess = STORE.get_session(payload.get("session_id"))

    anchor = payload.get("anchor") or sess.findings.get("anchor_timestamp")
    host = payload.get("host") or (sess.findings.get("hosts") or [None])[0]
    if not anchor:
        return jsonify({"error": "anchor is required (no findings in session yet)"}), 400

    result = mcp_client.call("timeline_around", {
        "anchor": anchor,
        "host": host,
        "ip": payload.get("ip"),
        "minutes_before": payload.get("minutes_before", 15),
        "minutes_after": payload.get("minutes_after", 15),
    })
    return jsonify({"session_id": sess.id, **result})


# ----------------------------------------------------------------- sigma ---
@app.post("/api/sigma")
def sigma_forge():
    """Forge a detection rule from the session's findings, then validate it.

    Streamed, since drafting involves generation - reuses the job/queue path.
    Pass {"stream": false} for a synchronous response, which is easier to test.
    """
    payload = request.get_json(silent=True) or {}
    sess = STORE.get_session(payload.get("session_id"))
    findings = payload.get("findings") or sess.findings

    if payload.get("stream") is False:
        result = sigma.forge(
            findings,
            start=payload.get("start", "now-48h"),
            end=payload.get("end", "now"),
            rule_yaml=payload.get("rule_yaml"),
        )
        return jsonify({"session_id": sess.id, **result})

    job = STORE.create_job(sess.id, "sigma_forge")

    def work():
        try:
            job.emit({"type": "sigma_drafting", "findings": findings})
            result = sigma.forge(
                findings,
                start=payload.get("start", "now-48h"),
                end=payload.get("end", "now"),
                rule_yaml=payload.get("rule_yaml"),
            )
            job.emit({"type": "sigma_rule", "yaml": result["yaml"],
                      "es_query": result["es_query"]})
            job.emit({"type": "sigma_validation", "validation": result["validation"],
                      "headline": result["headline"]})
            job.result = result
            job.status = "done"
            job.emit({"type": "done", "job_id": job.id})
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.error = str(exc)
            log.exception("sigma forge failed")
            job.emit({"type": "error", "message": str(exc)})
        finally:
            job.close()

    threading.Thread(target=work, daemon=True, name=f"sigma-{job.id[:8]}").start()
    return jsonify({"job_id": job.id, "session_id": sess.id, "status": "running"})


# ---------------------------------------------------------------- stream ---
def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@app.get("/api/stream/<job_id>")
def stream(job_id: str):
    """SSE. One consumer per job.

    Two gotchas, each worth an hour if missed:
      - X-Accel-Buffering: no, or a proxy buffers and nothing appears until the end.
      - never q.get() unbounded, or a dead worker hangs the browser forever.
    """
    job = STORE.get_job(job_id)
    if job is None:
        return jsonify({"error": "unknown job_id"}), 404

    def gen():
        # Replay anything emitted before this consumer connected - otherwise a
        # slow browser silently misses the first hop cards.
        replayed = len(job.events)
        for ev in job.events[:replayed]:
            yield _sse(ev)
        if job.status != "running":
            yield _sse({"type": "eof"})
            return

        deadline = time.time() + config.STREAM_TIMEOUT_S
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                yield _sse({"type": "timeout", "after_s": config.STREAM_TIMEOUT_S})
                break
            try:
                ev = job.queue.get(timeout=min(config.HEARTBEAT_S, remaining))
            except queue.Empty:
                yield ": keepalive\n\n"  # SSE comment; keeps proxies honest
                continue
            if ev is SENTINEL:
                break
            if ev.get("seq", 0) >= replayed:  # already replayed above
                yield _sse(ev)
        yield _sse({"type": "eof"})

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/events/<job_id>")
def events_polling(job_id: str):
    """Polling fallback (plan 05's option 3) for when SSE misbehaves - less
    elegant, never fails. ?since=N returns everything at or after sequence N."""
    job = STORE.get_job(job_id)
    if job is None:
        return jsonify({"error": "unknown job_id"}), 404
    since = request.args.get("since", default=0, type=int)
    pending = [e for e in job.events if e.get("seq", 0) >= since]
    return jsonify({
        "events": pending, "next_since": len(job.events), "status": job.status,
    })


@app.get("/api/job/<job_id>")
def job_status(job_id: str):
    job = STORE.get_job(job_id)
    if job is None:
        return jsonify({"error": "unknown job_id"}), 404
    return jsonify({
        "job_id": job.id, "session_id": job.session_id, "status": job.status,
        "question": job.question, "event_count": len(job.events),
        "result": job.result, "error": job.error,
    })


@app.get("/api/session/<session_id>")
def session_state(session_id: str):
    """What the analyst has found so far. Timeline and Sigma read this."""
    sess = STORE.get_session(session_id)
    return jsonify({
        "session_id": sess.id, "findings": sess.findings,
        "last_verdict": sess.last_verdict, "tool_calls": len(sess.tool_calls),
    })


# ---------------------------------------------------------------- replay ---
@app.get("/api/replay")
def replay_status():
    return jsonify({"enabled": config.DEMO_REPLAY, **replay.available()})


@app.post("/api/replay/record")
def replay_record():
    """Capture a good live run into demo_cache.json during rehearsal, so the
    escape hatch exists without hand-editing JSON."""
    payload = request.get_json(silent=True) or {}
    job_id = payload.get("job_id")
    job = STORE.get_job(job_id) if job_id else None
    if job is None:
        return jsonify({"error": "unknown or missing job_id"}), 404
    if job.status != "done":
        return jsonify({"error": f"job is {job.status}, only 'done' runs are cacheable"}), 400
    info = replay.record(
        job.question,
        [e for e in job.events if e.get("type") not in ("done", "eof")],
        (job.result or {}).get("findings", {}),
    )
    return jsonify({"recorded": True, "question": job.question, **info})


# ----------------------------------------------------------------- admin ---
@app.post("/api/admin/sweep")
def admin_sweep():
    """Drop finished jobs so a long demo session doesn't grow unbounded."""
    removed = STORE.sweep(max_age_s=request.args.get("max_age", 3600, type=int))
    return jsonify({"swept": removed, "remaining": STORE.job_count()})


# ----------------------------------------------------------------- errors ---
@app.errorhandler(404)
def not_found(_e):
    return jsonify({"error": "not found"}), 404


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": f"upload exceeds {config.MAX_UPLOAD_MB} MB"}), 413


@app.errorhandler(Exception)
def catch_all(e):
    """Always JSON, never Flask's HTML traceback page (plan 05 Phase 5)."""
    log.exception("unhandled error")
    return jsonify({"error": type(e).__name__, "message": str(e)}), 500


def boot() -> None:
    log.info("booting on http://%s:%s", config.HOST, config.PORT)
    log.info("mode=%s  agent=%s  mcp=%s",
             config.mode(), agent_bridge.active_backend(), config.MCP_URL)
    agent_bridge.warm_up()


if __name__ == "__main__":
    boot()
    # threaded=True is required: the agent runs in a worker thread while the SSE
    # route drains its queue. Single-threaded Flask would freeze the browser for
    # the whole run and render the trace all at once at the end.
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG,
            threaded=True, use_reloader=False)
