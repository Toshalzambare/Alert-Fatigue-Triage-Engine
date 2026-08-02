# Backend — Flask Service Layer

Plan 05, **all five phases complete**. Transport, session, and orchestration only —
no business logic. Queries belong to Teammate C (MCP), reasoning to Teammate D (agent).

Runs standalone today with no Elastic, no MCP server, and no model.

## Boot

```bash
cd backend
./run.sh                       # creates venv on first run, then polls health
```

Serves on **http://127.0.0.1:5000** (`FLASK_PORT` in the root `.env`).

> If the bind ever fails with a confusing 403, macOS AirPlay Receiver has taken
> port 5000 — set `PORT=5001` for that run. It is free on this machine today.

## Test it

Import `postman_collection.json` (19 requests, 7 folders) and run folder 2
top-to-bottom. **[EXPECTED_RESULTS.md](EXPECTED_RESULTS.md)** documents what every
endpoint returns, captured from a live run.

Fastest sanity check:

```bash
curl -s localhost:5000/api/health | python3 -m json.tool

JOB=$(curl -s -X POST localhost:5000/api/ask -H 'Content-Type: application/json' \
  -d '{"question":"What IPs seem malicious today and why?"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')

curl -N localhost:5000/api/stream/$JOB
```

Events must **trickle in over ~5 seconds**, not dump at the end. That incremental
arrival is the deliverable — if they batch, the frontend's hop cards cannot appear
in sequence, and the sequence *is* the demo.

## Routes

| Route | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Integration dashboard — which subsystem is down |
| `/api/ask` | POST | Start a run → `{job_id, session_id}` |
| `/api/stream/<job_id>` | GET | SSE event stream |
| `/api/events/<job_id>?since=N` | GET | Polling fallback if SSE misbehaves |
| `/api/job/<job_id>` | GET | Job status + final result |
| `/api/session/<session_id>` | GET | Accumulated findings |
| `/api/upload` | POST | Multimodal — multipart or base64 |
| `/api/timeline` | POST | Inspect Timeline button; bypasses the LLM |
| `/api/sigma` | POST | Forge + validate a detection rule |
| `/api/replay` · `/api/replay/record` | GET · POST | Demo escape hatch |
| `/api/admin/sweep` | POST | Drop finished jobs |

## Files

| File | Role |
|---|---|
| `app.py` | Routes, SSE, job queue, error handlers |
| `session.py` | `Job` + `Session` + thread-safe `Store` |
| `agent_bridge.py` | Resolves replay / real agent / mock behind one function |
| `mcp_client.py` | Thin client for C's FastMCP + contract-shaped stubs |
| `sigma.py` | Rule draft → ES query (in Python) → validation |
| `replay.py` | `demo_cache.json` record and playback |
| `mock_agent.py` | Scripted run of plan 02's Narrative 1 |
| `config.py` | Env config with working defaults |

## How it streams

```
POST /api/ask  →  worker thread runs agent  →  job.emit(ev)  →  Queue
                                                                  ↓
                        browser  ←──  SSE  ←──  /api/stream drains queue
```

`threaded=True` is **required**. Flask's dev server is otherwise synchronous, and
since inference will take 5–30s per call, a single-threaded server would freeze
the browser for the whole run and render the trace all at once at the end.

Four details that each cost an hour if missed:

- **`X-Accel-Buffering: no`** — without it a proxy buffers SSE and nothing appears until completion.
- **`queue.get(timeout=…)`, never unbounded** — a dead worker would hang the browser forever. Times out at `STREAM_TIMEOUT_S` and emits `{"type":"timeout"}`.
- **SENTINEL in a `finally`** — an unhandled exception in a worker thread is invisible in Flask's console and looks exactly like a hung UI. Verified: a crashing agent emits `error`, then closes.
- **`seq` assigned per job, never inherited** — replayed cache events carry stale sequence numbers; letting those through breaks the late-subscriber dedup and the polling cursor.

A late subscriber gets the full backlog replayed before live events resume, so a
slow browser never misses the early hop cards.

## Swapping in the real agent

`agent_bridge.run()` resolves in priority order: **`DEMO_REPLAY`** → **`Agent/graph.py`**
→ **mock**. Drop in D's graph exposing:

```python
def run(question: str, emit, image: bytes | None = None) -> dict
```

and it is picked up automatically at next boot — **no change to `app.py`**.
`emit` is the entire integration surface: one function, one dict argument, shapes
per contract §1. The agent never imports Flask; Flask never imports the agent
directly.

## Mock data

`mock_agent.py` scripts Narrative 1 from plan 02 — `45.133.1.88` brute-forces
`john.smith` on `vpn-gw-01`, succeeds at 14:21, then exfiltrates 4.2 MB. It
exercises every event type the frontend renders: `triage`, `tool_call`,
`tool_result`, `agent_hop`, `healing`, `injection`, `vision`, `token`, `verdict`.

Drop a `mock_events.jsonl` here to override it — Teammate A owns that file per
contract §1.

## Demo escape hatch

```bash
# during rehearsal, after a good run
curl -X POST localhost:5000/api/replay/record -H 'Content-Type: application/json' \
  -d '{"job_id":"<id>"}'

# on demo day, if the model dies
DEMO_REPLAY=1 ./run.sh
```

Cached runs stream through the **identical** SSE path with the same pacing.
Question matching is fuzzy, because a judge will not retype the scripted question
verbatim. An unmatched question falls back to the scripted run rather than
returning nothing.

## Config

**One `.env`, at the repo root** — shared by backend, Agent, mcp, and the data
seeder. There is deliberately no `backend/.env`: four copies of a credential
drift apart, and the resulting "works for me" bug costs an hour to find.
`config.py` loads it by absolute path, so it resolves the same no matter which
directory you launch from.

Read from the root `.env`:

| Var | Used for |
|---|---|
| `ELASTIC_URL` · `ELASTIC_API_KEY` | Elastic Cloud (consumed by MCP, not Flask) |
| `GEMMA_API_KEY` | Hosted inference via OpenRouter |
| `FLASK_PORT` · `FLASK_ENV` | Port, and debug mode when `development` |

Backend-only overrides with working defaults (no `.env` entry needed):
`MOCK_DELAY_MS=40` for fast test runs, `PORT`, `DEMO_REPLAY`, `MCP_URL`,
`GEMMA_MODEL`, `STREAM_TIMEOUT_S`, `CORS_ORIGINS`.

`/api/health` reports whether each credential is **present**, never its value.

## Known gaps

- **Elastic / MCP probes report config presence, not live connectivity.** MCP is probed for real (`/health`); Elastic is not queried from Flask at all — queries go through MCP by design.
- **Gemma is hosted (OpenRouter), so nothing is loaded into VRAM.** `GEMMA_MODEL` defaults to `google/gemma-3-27b-it`; confirm the exact model slug with Teammate D.
- **`sigma.to_es_query()` handles the brute-force shape only.** Parsing arbitrary Sigma is out of scope for a 4-hour demo.
- **CORS is `*`.** Fine for a local demo; narrow via `CORS_ORIGINS` if exposed.
- **No auth, no database.** Deliberate — a dict is correct here.
