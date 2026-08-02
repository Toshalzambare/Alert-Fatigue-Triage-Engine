# Backend — Flask Service Layer

Plan 05, **Phases 0 and 1 complete**. Transport, session, and orchestration only —
no business logic. Queries belong to Teammate C (MCP), reasoning to Teammate D (agent).

## Boot

```bash
cd backend
./run.sh                       # creates venv on first run
```

Serves on **http://127.0.0.1:5001**. Port 5001, not 5000 — macOS AirPlay Receiver
squats on 5000 and returns a confusing 403.

## Verify in 30 seconds

```bash
# 1. all four subsystems
curl -s localhost:5001/api/health | python3 -m json.tool

# 2. start a run
curl -s -X POST localhost:5001/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"What IPs seem malicious today and why?"}'

# 3. watch it stream (paste the job_id from step 2)
curl -N localhost:5001/api/stream/<job_id>
```

Step 3 should print events **one at a time over ~2 seconds**, not all at once at
the end. That incremental arrival is the whole point of the phase — if they batch,
the frontend's hop cards can't appear in sequence and the trace pane loses its value.

## Routes

| Route | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Integration dashboard — which subsystem is down |
| `/api/ask` | POST | Start a run → `{job_id, session_id}` |
| `/api/stream/<job_id>` | GET | SSE event stream |
| `/api/events/<job_id>?since=N` | GET | Polling fallback if SSE misbehaves |
| `/api/job/<job_id>` | GET | Job status + final result |
| `/api/session/<session_id>` | GET | Accumulated findings (Timeline/Sigma read this) |

Not yet built (Phase 3): `/api/upload`, `/api/timeline`, `/api/sigma`.

## How it streams

```
POST /api/ask  →  worker thread runs agent  →  job.emit(ev)  →  Queue
                                                                  ↓
                        browser  ←──  SSE  ←──  /api/stream drains queue
```

`threaded=True` is **required**. Flask's dev server is otherwise synchronous, and
since Gemma inference will take 5–30s per call, a single-threaded server would
freeze the browser for the entire run and render the trace all at once at the end.

Three details that each cost an hour if missed:

- **`X-Accel-Buffering: no`** — without it a proxy buffers SSE and nothing appears until completion.
- **`queue.get(timeout=...)`, never unbounded** — a dead worker would hang the browser forever. Times out at `STREAM_TIMEOUT_S` (120s) and emits `{"type":"timeout"}`.
- **SENTINEL in a `finally`** — an unhandled exception in a worker thread is invisible in Flask's console and looks exactly like a hung UI. Verified: a crashing agent emits `error` then closes the stream.

A late subscriber gets the full backlog replayed from `job.events` before live
events resume, so a slow browser never misses the first hop cards.

## Swapping in the real agent

`mock_agent.run()` already has the signature D's graph must expose:

```python
def run(question: str, emit, image: bytes | None = None) -> dict
```

`emit` is the entire integration surface between Flask and the agent — one
function, one dict argument, shapes per contract §1. The agent never imports
Flask. When D's graph lands, change the one call in `app.run_agent()`; nothing
else in the backend moves.

## Mock data

`mock_agent.py` scripts Narrative 1 from plan 02 — `45.133.1.88` brute-forces
`john.smith` on `vpn-gw-01`, succeeds at 14:21, then exfiltrates 4.2 MB. It
exercises every event type the frontend renders: `triage`, `tool_call`,
`tool_result`, `agent_hop`, `healing`, `injection`, `token`, `verdict`.

Drop a `mock_events.jsonl` in this directory to override the scripted run —
Teammate A owns that file per contract §1.

## Config

All env vars live in `config.py` with working defaults; copy `.env.example` to
`.env` to override. Nothing needs configuring for Phases 0–1 — it runs in mock
mode with no Elastic, no MCP, and no model.

Useful knobs: `MOCK_DELAY_MS=60` for fast test runs, `PORT`, `STREAM_TIMEOUT_S`.

## Known gaps

- **Elastic / MCP / Gemma probes return `stub`.** They report config presence, not real connectivity — they get wired when C and D land.
- **Gemma runtime undecided.** `GEMMA_MODEL` default is a placeholder; plan 04 assumes a local T4 that doesn't exist on this machine.
- **No auth, no database.** Deliberate — a dict is correct for a 4-hour demo.
