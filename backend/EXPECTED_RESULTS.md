# Expected Results

What every endpoint should return. All responses below were captured from a live
run of this backend in **mock mode** — no MCP server and no agent yet, which is
the correct state until Teammates C and D land. Elastic credentials *are* loaded.

## Setup

```bash
cd backend
./run.sh                    # http://127.0.0.1:5000
```

Config comes from the **single `.env` at the repo root** (`FLASK_PORT=5000`), not
from `backend/.env` — there is deliberately no per-directory env file.

Import `postman_collection.json`. Run **folder 2 top-to-bottom** — `Ask` saves
`job_id` and `session_id` into collection variables, so every request below it
works with an empty body, exactly as the frontend will call them.

> **Postman cannot render SSE.** `/api/stream/:job_id` will hang and then dump
> everything at once. Use **Poll events** to inspect events as JSON, and test the
> real streaming behavior with `curl -N` (see [Streaming](#3-streaming)).

**Timing:** a run takes ~5s at the default 300ms pacing. Requests that read
results (`Job status`, `Session findings`) need ~6s after `Ask`. Set
`MOCK_DELAY_MS=40` for near-instant runs while testing.

---

## 1. Health

`GET /api/health` → **200**

```json
{
  "ok": true,
  "ready": false,
  "degraded": ["mcp", "agent"],
  "uptime_s": 4.3,
  "subsystems": {
    "elastic": { "status": "configured", "index": "secops-logs-*",
                 "host": "my-security-project-b0f7f7.es.asia-south1.gcp.elastic.cloud",
                 "detail": "credentials present; queries go through MCP, not Flask" },
    "mcp":     { "status": "stub", "mode": "http", "url": "http://localhost:8000/mcp",
                 "detail": "serving contract-shaped stub data" },
    "agent":   { "status": "mock", "backend": "mock",
                 "model": "google/gemma-3-27b-it", "api_key_present": true },
    "backend": { "status": "ok" }
  },
  "config": { "mode": "mock", "env_file": "/…/SO/.env",
              "es_configured": true, "gemma_configured": true, "port": 5000 },
  "replay": { "enabled": false },
  "jobs": 0,
  "sessions": 0
}
```

**`ready: false` with `mcp` and `agent` degraded is the correct answer right now** —
honest reporting, not a failure. `elastic` already reads `configured` because the
root `.env` has real credentials.

| Subsystem | Becomes `ok` when |
|---|---|
| `elastic` | ✅ already — `ELASTIC_URL` + `ELASTIC_API_KEY` are set |
| `mcp` | C's FastMCP server answers at `MCP_URL` |
| `agent` | `Agent/graph.py` exists and exposes `run()` |

**Config comes from one `.env` at the repo root**, not `backend/.env` — `env_file`
in the response tells you exactly which file was loaded, which settles "did it
pick up my key?" in one request.

`config` reports only whether each credential is **present** (`es_configured`,
`gemma_configured`, `api_key_present`) and never echoes a key value. This is the
one endpoint everyone screenshots during integration, so verify it stays that way.

---

## 2. Core Demo Flow

### Ask — Q1 malicious IPs

`POST /api/ask` `{"question": "What IPs seem malicious today and why?"}` → **200**

```json
{ "job_id": "3742daa40c98…", "session_id": "5dc8b4ac269a…", "status": "running" }
```

Returns **immediately**. The run continues in a worker thread — that is why the
browser never freezes during 5–30s of inference.

### Poll events

`GET /api/events/:job_id?since=0` → **200**

18 events in this exact order:

```
triage → tool_call → tool_result → agent_hop → tool_call → tool_result
→ agent_hop → tool_call → tool_result → healing → tool_result → injection
→ token ×4 → verdict → done
```

Every event carries a `seq` (0…17) and a `ts`. `seq` is **assigned by the job**,
never inherited — cached replay events get renumbered, which keeps the polling
cursor and the SSE dedup correct.

What each type proves on screen:

| Event | Rubric claim it evidences |
|---|---|
| `tool_result.meta` | `1284 hits → 20 returned · 12 fields · 34ms` — the efficiency line |
| `tool_result.meta.es_query` | Real DSL for the Query Mentor card |
| `agent_hop` | Autonomy — the agent chose the next step **and said why** |
| `healing` | Self-healing: `j.smith` → `john.smith` recovery |
| `injection` | Prompt injection in log data, neutralized |
| `verdict` | The reasoned threat assessment |

The `check_ip` result carries `"raw_documents": 0` — 64 documents collapsed into
one profile. That is the strongest single "only pulls what it needs" datapoint.

Send this mid-run and you get `"status": "running"` with a partial list. That is
expected — re-send for the rest.

### Job status

`GET /api/job/:job_id` → **200**, `"status": "done"`, `"event_count": 18`, and
`result.verdict.severity == "high"`.

### Session findings

`GET /api/session/:session_id` → **200**

```json
{
  "findings": {
    "ips_of_interest": ["45.133.1.88"],
    "users": ["john.smith"],
    "hosts": ["vpn-gw-01"],
    "anchor_timestamp": "2026-08-02T14:26:00Z"
  },
  "last_verdict": { "severity": "high", "…": "…" },
  "tool_calls": 8
}
```

**This is the integration that matters.** Timeline and Sigma read it, which is why
they work with only a `session_id`.

### Timeline

`POST /api/timeline` `{"session_id": "…"}` → **200**

Anchor and host resolve **from session findings** — no anchor in the body:

```json
{
  "data": {
    "anchor": "2026-08-02T14:26:00Z",
    "host": "vpn-gw-01",
    "before": [ 3 events — cron, routine auth, file created ],
    "after":  [ 3 events — nc -lvp 4444, port 4444, 4.2MB outbound ],
    "summary": { "before_count": 3, "after_count": 3, "new_categories_after": ["network"] }
  },
  "meta": { "took_ms": 27, "stub": true, "…": "…" }
}
```

Quiet before / loud after is the entire visual payoff of time-travel. This route
**bypasses the LLM entirely** (~200ms) because it backs a button a judge clicks.

`meta.stub: true` disappears once C's server is live.

### Sigma forge

`POST /api/sigma` `{"session_id": "…", "stream": false}` → **200**

```json
{
  "yaml": "title: Brute Force Followed by Successful Authentication\n…",
  "es_query": { "query": { "bool": { "filter": [
      {"term": {"event.category": "authentication"}},
      {"term": {"event.outcome": "failure"}}
  ]}}},
  "validation": { "matches": 61, "true_positives": 60, "false_positives": 1,
                  "fp_rate": 0.016, "sample_fps": [ … ] },
  "headline": "61 matches over history — 60 true positives, 1 false positives (1.6% FP rate)."
}
```

The `headline` is the line worth putting on screen. Validation is what turns
"I wrote a rule" into "I wrote a rule and **proved** it at 1.6% FP."

Two guarantees the collection asserts: the YAML → ES conversion happens in
**Python, never the LLM** (a 12B model emits invalid DSL often enough to wreck a
demo), and the query is **never `match_all`** — that would validate at 100% FP.

Omit `"stream": false` for the streamed job/queue path (`sigma_drafting` →
`sigma_rule` → `sigma_validation` → `done`).

---

## 3. Streaming

`GET /api/stream/:job_id` → **200**, `Content-Type: text/event-stream`

**Test with curl, not Postman:**

```bash
curl -N localhost:5000/api/stream/<job_id>
```

```
data: {"type": "triage", "intent": "threat_hunt", …, "seq": 0}
data: {"type": "tool_call", "tool": "search_logs", "hop": 1, …, "seq": 1}
…
data: {"type": "verdict", "severity": "high", …, "seq": 16}
data: {"type": "eof"}
```

**The one thing to verify:** events must **trickle in over ~5 seconds**, not
appear all at once. Batched arrival means the frontend's hop cards cannot appear
in sequence — and that sequence *is* the demo. Watch the lines print one by one.

Other behavior:

- **Late subscriber** — connect after the job finishes and you still get the full
  backlog, then `eof`. A slow browser never misses the early hop cards.
- **Keepalive** — `: keepalive` comments every 15s during quiet periods.
- **Timeout** — a `{"type":"timeout"}` event after `STREAM_TIMEOUT_S` (120s), so
  a dead worker can never hang the browser forever.
- **Agent crash** — emits `{"type":"error"}` then closes cleanly. Verified: this
  is the #1 way a live demo dies mysteriously, and it is handled.

### Polling fallback

`GET /api/events/:job_id?since=5` → **200**, returns only `seq >= 5`, plus
`next_since` to use as the next cursor. Less elegant than SSE, never fails.

---

## 4. Multimodal Upload

`POST /api/upload` (multipart `image` + `question`, **or** JSON `image_base64`) → **200**

```json
{
  "job_id": "…", "session_id": "…", "status": "running",
  "image": { "format": "PNG", "width": 10, "height": 10, "bytes": 78 }
}
```

The base64 request in the collection runs **as-is** — it embeds a tiny valid PNG,
so no file picker is needed. A `data:image/png;base64,` prefix is tolerated.

Then poll events: the first event is `vision`, before any tool call:

```json
{ "type": "vision", "brand_impersonated": "Microsoft 365",
  "extracted_domain": "micros0ft-verify.co", "typosquat": true,
  "red_flags": ["urgency banner", "mismatched sender"] }
```

The domain then feeds **the same** `search_logs` loop — vision is a new input
modality to the existing pipeline, not a bolt-on feature. Uploads reuse the
identical job/queue path as `/api/ask`; there is deliberately no second streaming
mechanism.

For the real demo, attach the fake M365 login screenshot with
`micros0ft-verify.co` visible in the URL bar (zero, not the letter o).

---

## 5. Replay — the escape hatch

`GET /api/replay` → **200** — lists cached runs.

`POST /api/replay/record` `{"job_id": "…"}` → **200**

```json
{ "recorded": true, "question": "What IPs seem malicious today and why?",
  "cached_runs": 1, "events": 17 }
```

Only `done` jobs are cacheable — recording a half-finished run would replay a
broken demo (a `running` job returns **400**).

Then restart with replay on:

```bash
DEMO_REPLAY=1 ./venv/bin/python app.py
```

`/api/health` now reports `"mode": "replay"`, `agent.backend: "replay"`, and the
cached question list.

**Verified behavior:**

- Reworded questions still match — asking *"which IPs look malicious right now?"*
  matches the cached *"What IPs seem malicious today and why?"* via token overlap.
  A judge will not retype the scripted question verbatim.
- The first event is `{"type": "replay", "cached_question": "…", "recorded_at": "…"}`.
- An unrelated question emits `{"type": "replay_miss"}` and **still produces a full
  verdict** by falling back to the scripted run. A demo must always answer.
- Events stream through the **identical SSE path** with the same pacing —
  indistinguishable from live on the wire.

This is not cheating: it is a recorded run of the real system. Build it before you
need it; you cannot build it at the moment you need it.

---

## 6. Error Handling

Every error is **JSON, never Flask's HTML traceback page**.

| Request | Status | Body |
|---|---|---|
| `POST /api/ask` `{}` | **400** | `{"error": "question is required"}` |
| `POST /api/ask` `{"question": "   "}` | **400** | `{"error": "question is required"}` |
| `GET /api/job/deadbeef` | **404** | `{"error": "unknown job_id"}` |
| `GET /api/stream/deadbeef` | **404** | `{"error": "unknown job_id"}` |
| `POST /api/timeline` `{}` | **400** | `{"error": "anchor is required (no findings in session yet)"}` |
| `POST /api/upload` `{}` | **400** | `{"error": "no image provided (multipart 'image' or 'image_base64')"}` |
| `POST /api/upload` corrupt bytes | **400** | `{"error": "not a valid image", "detail": "cannot identify image file …"}` |
| upload > 10 MB | **413** | `{"error": "upload exceeds 10 MB"}` |
| `GET /api/does-not-exist` | **404** | `{"error": "not found"}`, `Content-Type: application/json` |

A corrupt image failing **here**, with a clear message, is the point — not deep
inside the vision model mid-demo.

---

## 7. Admin

`POST /api/admin/sweep?max_age=0` → **200** `{"swept": 1, "remaining": 1}`

Drops finished jobs so a long session does not grow unbounded. **Running jobs are
never swept** — `remaining` counts those still in flight.

---

## Quick sanity script

```bash
curl -s localhost:5000/api/health | python3 -m json.tool

JOB=$(curl -s -X POST localhost:5000/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"What IPs seem malicious today and why?"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')

curl -N localhost:5000/api/stream/$JOB
```

If those three commands work and the events **trickle** rather than dump, the
backend is demo-ready.

---

## What changes when teammates land

The wire format does **not** change — that is the point of building against
contract-shaped stubs.

| When | What changes | What stays identical |
|---|---|---|
| **B** ships Elastic Cloud | `.env` gets credentials; health flips `elastic` to `configured` | all routes |
| **C** ships FastMCP | `meta.stub` disappears; real `es_query` and `took_ms` | envelope shape, all routes |
| **D** ships `Agent/graph.py` | `agent_bridge` auto-detects it; health flips to `live` | event types, SSE path, `emit()` |

`agent_bridge.py` resolves the agent at import: `DEMO_REPLAY` → real
`Agent/graph.py` → mock. Dropping in D's graph requires **no change to `app.py`**.
