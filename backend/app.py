"""Flask service layer - transport, session, orchestration. No business logic.

Every reasoning decision belongs to the agent (Agent/graph.py); every Elastic
query belongs to MCP (mcp/tools/impl.py). If there is an ES query or a prompt in
this file, it is in the wrong module.

Architecture
------------
    browser ──HTTP──► Flask ──enqueue──► Redis ──► Celery worker ──► LangGraph
       ▲                                                                │
       └──────────── SSE ◄── Redis pub/sub ◄──── emit(event) ◄──────────┘

Flask never runs the agent. It enqueues a task and streams the events the worker
publishes, which is what lets the API scale independently of inference capacity.
"""
import base64
import io
import json
import logging
import time
import uuid

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

import celery_app as bus
import config
import llm
import mcp_client
from tasks import forge_sigma, run_agent

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("backend")
logging.getLogger("urllib3").setLevel(logging.WARNING)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024
CORS(app, resources={r"/api/*": {"origins": config.CORS_ORIGINS}})

BOOT_TIME = time.time()

# Session state: the last findings, so /api/timeline and /api/sigma know what we
# just found without an NL round-trip. Lives in Redis rather than a dict so it
# survives a web restart and is shared across web processes.
SESSION_TTL_S = 86400


def session_key(sid: str) -> str:
    return f"session:{sid}"


def get_session(sid: str | None) -> tuple[str, dict]:
    """Fetch or mint. An unknown id silently creates a new session - a demo
    should never 404 because a browser tab was refreshed."""
    sid = sid or uuid.uuid4().hex
    raw = bus.redis().get(session_key(sid))
    return sid, (json.loads(raw) if raw else {})


def save_session(sid: str, data: dict) -> None:
    bus.redis().setex(session_key(sid), SESSION_TTL_S, json.dumps(data))


# ---------------------------------------------------------------- health ---
@app.get("/api/health")
def health():
    """The integration dashboard. Says which subsystem is down in one second,
    instead of four people guessing."""
    broker_up = bus.broker_available()
    workers = bus.workers_online() if broker_up else 0
    mcp_up = mcp_client.available()
    llm_status = llm.status()

    subsystems = {
        "elastic": (
            {"status": "configured", "index": config.ES_INDEX,
             "detail": "queried through MCP, not Flask"}
            if config.ELASTIC_URL and config.ELASTIC_API_KEY
            else {"status": "not_configured",
                  "detail": f"ELASTIC_URL / ELASTIC_API_KEY unset in {config.ENV_PATH}"}
        ),
        "mcp": {
            "status": "ok" if mcp_up else "down",
            "url": config.MCP_URL,
            "detail": None if mcp_up else "start it: python mcp/server.py",
        },
        "llm": llm_status,
        "broker": {
            "status": "ok" if broker_up else "down",
            "url": config.REDIS_URL,
            "detail": None if broker_up else "start it: redis-server",
        },
        "workers": {
            "status": "ok" if workers else "down",
            "online": workers,
            "detail": None if workers else "start one: celery -A tasks worker",
        },
        "backend": {"status": "ok"},
    }

    degraded = [k for k, v in subsystems.items()
                if v["status"] not in ("ok", "configured")]

    return jsonify({
        "ok": True,
        "ready": not degraded,
        "degraded": degraded,
        "uptime_s": round(time.time() - BOOT_TIME, 1),
        "subsystems": subsystems,
        "config": config.summary(),
    })


# ------------------------------------------------------------------- ask ---
def _enqueue(question: str, session_id: str | None, image_b64: str | None = None, audio_b64: str | None = None):
    sid, _ = get_session(session_id)
    job_id = uuid.uuid4().hex
    bus.set_state(job_id, status="queued", question=question, session_id=sid)
    run_agent.delay(job_id, question, image_b64, audio_b64)
    log.info("job %s queued: %r", job_id[:8], question[:60])
    return job_id, sid


@app.post("/api/ask")
def ask():
    """Enqueue an investigation. Returns immediately; the caller then opens
    /api/stream/<job_id> to watch it."""
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400
    if not bus.broker_available():
        return jsonify({"error": "task broker unavailable", "detail": "redis is down"}), 503

    job_id, sid = _enqueue(question, payload.get("session_id"))
    return jsonify({"job_id": job_id, "session_id": sid, "status": "queued"})


@app.post("/api/upload")
def upload():
    """Multimodal entry point. Accepts multipart or base64 JSON, validates the
    bytes are a real image, then reuses the identical job path as /api/ask."""
    raw: bytes | None = None
    question = ""
    session_id = None

    if "image" in request.files:
        raw = request.files["image"].read()
        question = (request.form.get("question") or "").strip()
        session_id = request.form.get("session_id")
    else:
        payload = request.get_json(silent=True) or {}
        question = (payload.get("question") or "").strip()
        session_id = payload.get("session_id")
        b64 = payload.get("image_base64") or ""
        if b64:
            if "," in b64[:64]:  # tolerate a data: URL prefix
                b64 = b64.split(",", 1)[1]
            try:
                raw = base64.b64decode(b64, validate=True)
            except Exception:  # noqa: BLE001
                return jsonify({"error": "image_base64 is not valid base64"}), 400

    if not raw:
        return jsonify({"error": "no image provided (multipart 'image' or 'image_base64')"}), 400

    # Fail here, with a clear message - not deep inside the vision model mid-demo.
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        img.verify()
        fmt, size = img.format, img.size
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "not a valid image", "detail": str(exc)}), 400

    question = question or "Did anyone click this?"
    job_id, sid = _enqueue(question, session_id, image_b64=base64.b64encode(raw).decode())
    return jsonify({
        "job_id": job_id, "session_id": sid, "status": "queued",
        "image": {"format": fmt, "width": size[0], "height": size[1], "bytes": len(raw)},
    })


@app.post("/api/audio")
def audio():
    """Native Multimodal Audio entry point.
    Accepts an audio file and passes the raw bytes directly to the agent.
    """
    question = ""
    raw: bytes | None = None
    session_id = None
    b64 = None

    if "audio" in request.files:
        fh = request.files["audio"]
        raw = fh.read()
        b64 = base64.b64encode(raw).decode("utf-8")
        question = (request.form.get("question") or "").strip()
        session_id = request.form.get("session_id")
    else:
        payload = request.get_json(silent=True) or {}
        b64 = payload.get("audio_base64") or ""
        question = (payload.get("question") or "").strip()
        session_id = payload.get("session_id")
        if b64:
            if "," in b64[:64]:
                b64 = b64.split(",", 1)[1]
            try:
                raw = base64.b64decode(b64, validate=True)
            except Exception:  # noqa: BLE001
                return jsonify({"error": "audio_base64 is not valid base64"}), 400

    if not raw or not b64:
        return jsonify({"error": "no audio provided"}), 400

    question = question or "Analyze this audio. If it's a voice command, execute it. If it's a voicemail/call recording, check it for social engineering/phishing indicators."
    
    job_id, sid = _enqueue(question, session_id, audio_b64=b64)
    return jsonify({
        "job_id": job_id, "session_id": sid, "status": "queued",
        "input_type": "audio",
        "audio": {"bytes": len(raw)}
    })


# ---------------------------------------------------------------- stream ---
def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@app.get("/api/stream/<job_id>")
def stream(job_id: str):
    """SSE, fed by Redis pub/sub.

    Replays the backlog first so a browser that subscribes late still receives
    the early hop cards, then follows the live channel.

    Two details that each cost an hour if missed:
      - X-Accel-Buffering: no, or a proxy buffers and nothing appears until the end.
      - never block unbounded, or a dead worker hangs the browser forever.
    """
    def gen():
        replayed = 0
        for ev in bus.read_backlog(job_id):
            replayed = max(replayed, ev.get("seq", 0) + 1)
            yield _sse(ev)
            if ev.get("type") == "eof":
                return

        pubsub = bus.redis().pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(bus.channel(job_id))
        deadline = time.time() + config.STREAM_TIMEOUT_S
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    yield _sse({"type": "timeout", "after_s": config.STREAM_TIMEOUT_S})
                    return
                msg = pubsub.get_message(
                    timeout=min(config.HEARTBEAT_S, remaining)
                )
                if msg is None:
                    yield ": keepalive\n\n"  # SSE comment; keeps proxies honest
                    continue
                ev = json.loads(msg["data"])
                if ev.get("seq", 0) < replayed:
                    continue  # already sent in the backlog replay
                yield _sse(ev)
                if ev.get("type") == "eof":
                    return
        finally:
            pubsub.close()

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
    """Polling fallback for when SSE misbehaves - less elegant, never fails.
    ?since=N returns everything at or after sequence N."""
    since = request.args.get("since", default=0, type=int)
    events = bus.read_backlog(job_id, since=since)
    state = bus.get_state(job_id)
    if not events and not state:
        return jsonify({"error": "unknown job_id"}), 404
    return jsonify({
        "events": events,
        "next_since": since + len(events),
        "status": state.get("status", "unknown"),
    })


@app.get("/api/job/<job_id>")
def job_status(job_id: str):
    state = bus.get_state(job_id)
    if not state:
        return jsonify({"error": "unknown job_id"}), 404
    return jsonify({
        "job_id": job_id,
        "status": state.get("status"),
        "question": state.get("question"),
        "event_count": len(bus.read_backlog(job_id)),
        "result": state.get("result"),
        "error": state.get("error"),
    })


@app.get("/api/session/<session_id>")
def session_state(session_id: str):
    sid, data = get_session(session_id)
    return jsonify({"session_id": sid, **data})


# -------------------------------------------------------------- timeline ---
@app.post("/api/timeline")
def timeline():
    """The *Inspect Timeline* button. Bypasses the LLM entirely - straight to
    MCP, ~200ms. Fast and unbreakable is what you want behind a button a judge
    clicks."""
    payload = request.get_json(silent=True) or {}
    sid, sess = get_session(payload.get("session_id"))
    findings = sess.get("findings", {})

    anchor = payload.get("anchor") or findings.get("anchor_timestamp")
    host = payload.get("host") or (findings.get("hosts") or [None])[0]
    if not anchor:
        return jsonify({"error": "anchor is required (no findings in session yet)"}), 400

    result = mcp_client.call("timeline_around", {
        "anchor": anchor,
        "timestamp": anchor,
        "host": host,
        "ip": payload.get("ip"),
        "minutes_before": payload.get("minutes_before", 15),
        "minutes_after": payload.get("minutes_after", 15),
    })
    return jsonify({"session_id": sid, **result})


# ----------------------------------------------------------------- sigma ---
@app.post("/api/sigma")
def sigma_forge():
    """Forge a detection rule from the session's findings, then validate it.

    Streamed by default (it involves generation); pass {"stream": false} for a
    synchronous response, which is easier to test.
    """
    payload = request.get_json(silent=True) or {}
    sid, sess = get_session(payload.get("session_id"))
    findings = payload.get("findings") or sess.get("findings", {})
    start = payload.get("start", "now-48h")
    end = payload.get("end", "now")

    if payload.get("stream") is False:
        import sigma

        return jsonify({"session_id": sid, **sigma.forge(findings, start=start, end=end)})

    job_id = uuid.uuid4().hex
    bus.set_state(job_id, status="queued", question="sigma_forge", session_id=sid)
    forge_sigma.delay(job_id, findings, start, end)
    return jsonify({"job_id": job_id, "session_id": sid, "status": "queued"})


# ---------------------------------------------------------------- errors ---
@app.errorhandler(404)
def not_found(_e):
    return jsonify({"error": "not found"}), 404


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": f"upload exceeds {config.MAX_UPLOAD_MB} MB"}), 413


@app.errorhandler(Exception)
def catch_all(e):
    """Always JSON, never Flask's HTML traceback page."""
    log.exception("unhandled error")
    return jsonify({"error": type(e).__name__, "message": str(e)}), 500


def boot() -> None:
    llm.apply_env()
    log.info("booting on http://%s:%s", config.HOST, config.PORT)
    log.info("  llm    : %s", llm.active_provider())
    log.info("  mcp    : %s", config.MCP_URL)
    log.info("  broker : %s", config.REDIS_URL)


if __name__ == "__main__":
    boot()
    # threaded=True is still required: each SSE connection holds a worker thread
    # for the life of the stream, even though the agent now runs in Celery.
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG,
            threaded=True, use_reloader=False)
