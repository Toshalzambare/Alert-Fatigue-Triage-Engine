# Plan 05 — Flask Backend / Service Layer · Teammate E (or whoever finishes first)

**Read `00_SHARED_CONTRACT.md` first.**

**You own the seam nobody else does.** B owns Elastic, C owns MCP, D owns the agent — but *nothing today runs them as one application*. That gap is where 4-hour hackathons die at T+3:00, when four working pieces refuse to start together.

Your deliverable: **one `python app.py` that boots the entire demo.**

---

## ⚠️ Read this before writing a line of Flask

**Flask's dev server is single-threaded and synchronous. Gemma inference on a T4 takes 5–30 seconds per call.** Naively, the browser freezes for the entire agent run, SSE never streams, and the reasoning trace — the team's highest-value visual — renders all at once at the end. That silently destroys Plan 01's whole purpose.

Three fixes, in order of preference:

1. **`threaded=True` + a queue per session** (recommended). Agent runs in a worker thread and pushes events to `queue.Queue`; the SSE route drains it. ~30 lines, no new dependency.
2. `gunicorn --workers 1 --threads 8` if you already know gunicorn.
3. Polling fallback (`/api/events?since=N`) if SSE misbehaves — less elegant, never fails.

**Decide at T+0:45 and tell Teammate A**, because it changes their client code.

---

## Architecture

```
                    ┌───────────────────────────────┐
   browser  ◄─SSE──►│         Flask (app.py)        │
   (Plan 01)        │                               │
                    │  /api/ask      POST  → job id │
                    │  /api/stream   GET   SSE      │
                    │  /api/upload   POST  image    │
                    │  /api/timeline POST  anchor   │
                    │  /api/sigma    POST  forge    │
                    │  /api/health   GET   status   │
                    └──────┬────────────────┬───────┘
                           │                │
                    worker thread      SessionStore
                           │            (in-memory dict)
                           ▼
                  ┌────────────────┐
                  │ LangGraph (D)  │
                  └───────┬────────┘
                          │ MCP client
                          ▼
                  ┌────────────────┐      ┌──────────┐
                  │ FastMCP (C)    ├─────►│ Elastic  │
                  └────────────────┘      └──────────┘
```

**Flask holds no business logic.** It's transport + session + orchestration. Every reasoning decision is D's; every query is C's. If you find yourself writing an ES query or a prompt, you're in someone else's plan.

---

## Phase 0 (T+0:30 → T+0:45) — Skeleton that boots, today

Before anything works, make the shell run. This lets A point their browser at a real server on hour one.

```python
app = Flask(__name__, static_folder="../ui/dist")

@app.get("/api/health")
def health():
    return {"elastic": probe_es(), "mcp": probe_mcp(),
            "gemma": GEMMA_LOADED, "mode": CONFIG.mode}
```

`/api/health` is not busywork — **it's your integration dashboard.** When someone says "it's broken," this endpoint says which of the four subsystems is actually down, in one second, instead of four people guessing.

Ship it returning `{"...": "stub"}` immediately.

---

## Phase 1 (T+0:45 → T+1:30) — Streaming skeleton with fake events

**Build the entire streaming path before the agent exists.** Replay `mock_events.jsonl` (A already has it, contract §1) through the real SSE route with a 300ms delay between events.

```python
JOBS: dict[str, Job] = {}          # job_id -> Job(queue, status, result)

@app.post("/api/ask")
def ask():
    job_id = uuid4().hex
    JOBS[job_id] = Job(queue=Queue(), status="running")
    threading.Thread(target=run_agent, args=(job_id, request.json), daemon=True).start()
    return {"job_id": job_id}

@app.get("/api/stream/<job_id>")
def stream(job_id):
    def gen():
        q = JOBS[job_id].queue
        while True:
            ev = q.get()                       # blocks
            if ev is SENTINEL: break
            yield f"data: {json.dumps(ev)}\n\n"
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

Two gotchas that cost an hour each if missed:
- **`X-Accel-Buffering: no`** — without it, proxies buffer SSE and nothing appears until completion.
- **Never `q.get()` without a timeout in the final version.** Use `q.get(timeout=120)` and emit a `{"type":"timeout"}` event, or a dead agent thread hangs the browser forever.

By T+1:30 A has a real, streaming server. **This is your stub-first equivalent of C's — it unblocks the frontend for a full hour.**

---

## Phase 2 (T+1:30 → T+2:30) — Wire D's graph

D's graph needs to *emit* events, not just return. Give them a callback rather than asking them to import Flask:

```python
# app.py
def run_agent(job_id, payload):
    q = JOBS[job_id].queue
    emit = lambda ev: q.put(ev)                # D calls this
    try:
        result = agent.run(payload["question"], image=payload.get("image"), emit=emit)
        JOBS[job_id].result = result
    except Exception as e:
        emit({"type": "error", "message": str(e)})
        log.exception("agent failed job=%s", job_id)
    finally:
        emit(SENTINEL)
```

**Agree the `emit(event)` signature with D at T+0:45.** One function, one dict argument, shapes per contract §1. That's the whole integration surface between Flask and the agent — keep it that small.

**Wrap the agent in try/except and always emit SENTINEL in `finally`.** An unhandled exception in a worker thread is invisible in Flask's console and looks like a hung UI. This is the #1 way a live demo dies mysteriously.

---

## Phase 3 (T+2:30 → T+3:00) — The remaining routes

**`/api/upload`** — multimodal. Accept multipart, cap at 10 MB, validate it's a real image (`PIL.Image.open` in a try), base64 it, hand bytes to D. Return a `job_id` and stream like `/api/ask`. **Don't invent a second streaming mechanism** — reuse the job/queue path.

**`/api/timeline`** — takes `{anchor, host}` from A's *Inspect Timeline* button. This one **bypasses the LLM entirely**: call C's `timeline_around()` directly and return JSON. No agent, no streaming, ~200ms. Fast and unbreakable, which is exactly what you want for a button a judge clicks.

**`/api/sigma`** — takes the session's `findings`, runs D's forge, returns `{yaml, validation}`. Streamed, since it involves generation.

**Session state.** A plain dict keyed by session id, holding the last `findings` and `tool_calls`. Timeline and Sigma both need "what did we just find." **No database.** A dict is correct for a 4-hour demo; anything more is time you don't have.

---

## Phase 4 (T+3:00 → T+3:30) — Config and one-command startup

Everything that varies lives in one `config.py` read from env with working defaults:

```python
ES_URL       = env("ES_URL", "http://localhost:9200")
MCP_MODE     = env("MCP_MODE", "stdio")        # stdio | http   ← contract §5
MCP_URL      = env("MCP_URL", "http://localhost:8000/mcp")
GEMMA_MODEL  = env("GEMMA_MODEL", "google/gemma-4-12b-it")
GEMMA_4BIT   = env_bool("GEMMA_4BIT", True)
DEMO_REPLAY  = env_bool("DEMO_REPLAY", False)  # ← the escape hatch
PORT         = env_int("PORT", 5000)
```

`run.sh` — starts Elastic (if Docker), seeds data if the index is empty, launches MCP if HTTP mode, then Flask. Poll `/api/health` until all green, then print the URL. **Test it from a clean shell.** "It works on my machine" is the classic hour-4 failure.

**Load Gemma once at module import, never per request.** Reloading a 12B model per request is a demo-ending mistake and an easy one to make.

---

## Phase 5 (T+3:30 → T+4:00) — Demo-day hardening

**`DEMO_REPLAY=1` is your insurance policy.** D caches successful runs to `demo_cache.json` (Plan 04, Phase 4). In replay mode, `/api/ask` matches the question and streams cached events through the *identical* SSE path with realistic delays.

This is not cheating — it's a recorded run of your real system, and every hackathon veteran ships one. If the T4 OOMs while judges watch, you flip one env var and the demo proceeds. **Build it before you need it; you cannot build it at the moment you need it.**

Also:
- **Warm-up call at boot** — one throwaway inference so the first judge question isn't the slow one.
- **Global error handler** returning JSON, never Flask's HTML traceback page.
- **`/api/health` on screen** during setup so you can prove all four subsystems are live.

---

## Deliverables

```
/backend/app.py          routes, SSE, job queue
/backend/config.py       env config
/backend/session.py      in-memory session store
/backend/run.sh          one-command startup
/backend/README.md       how to boot, env vars, troubleshooting
```

---

## What you must NOT do

Because in a 4-hour build these all *feel* productive and are not:

- ❌ A database — the dict is correct here
- ❌ Auth / login — no judge will ask
- ❌ Docker Compose for the whole stack — unless it already works
- ❌ Business logic in routes — belongs to C and D
- ❌ Async/await rewrite — `threaded=True` is sufficient

**Cut order:** `/api/sigma` → `/api/timeline` → `/api/upload`. Never cut `/api/ask`, `/api/stream`, or `/api/health` — they are the demo.
