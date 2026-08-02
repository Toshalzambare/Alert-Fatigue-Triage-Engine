# 00 — Shared Contract (READ FIRST, ALL FOUR TEAMMATES)

**Freeze this before anyone writes code. 30 minutes of agreement here saves 3 hours of integration hell.**

Track 1 restated: *analyst types a natural-language question → Gemma 4 function-calls → Elastic query → analyze payload → reasoned threat assessment.* MCP standardizes the Elastic connection. The agent must pull **only the data it needs**.

---

## 1. The four seams

```
┌─────────────┐   SSE/JSON    ┌──────────────┐   MCP tools   ┌────────────┐   ES DSL   ┌─────────┐
│  Frontend   │ ◄───────────► │  Agent       │ ◄───────────► │  FastMCP   │ ◄────────► │ Elastic │
│  (Plan 01)  │               │  (Plan 04)   │               │  (Plan 03) │            │ (Plan02)│
└─────────────┘               └──────────────┘               └────────────┘            └─────────┘
   Teammate A                    Teammate D                     Teammate C              Teammate B
```

Each arrow is a frozen contract. Nobody reaches across two arrows.

---

## 2. Canonical log document (Teammate B owns, everyone consumes)

Index `secops-logs-*`. **Every** document has these fields. Optional fields are `null`, never absent.

```json
{
  "@timestamp":  "2026-08-02T14:23:11.000Z",
  "event": { "category": "authentication", "action": "login_failed", "outcome": "failure" },
  "source": { "ip": "45.133.1.88", "geo": { "country": "DE", "city": "Frankfurt" } },
  "user":   { "name": "j.smith", "id": "u-1042" },
  "host":   { "name": "vpn-gw-01", "ip": "10.0.4.12" },
  "url":    { "full": "https://micros0ft-verify.co/login", "domain": "micros0ft-verify.co" },
  "network":{ "bytes": 8421, "direction": "outbound" },
  "process":{ "name": "sshd", "pid": 4412 },
  "message": "Failed password for j.smith from 45.133.1.88 port 51422",
  "labels": { "scenario": "bruteforce_then_success", "is_threat": true }
}
```

`event.category` is a **closed set** — the agent's tool schemas enumerate it:
`authentication | network | file | process | dns | web | email`

`labels.scenario` is the ground-truth tag. It powers the demo, the Sigma validation, and any accuracy claim. **Never show `labels` to Gemma** — it's the answer key. Teammate C strips it in the MCP layer (see §4).

---

## 3. MCP tool signatures (Teammate C owns, Teammate D calls)

Five tools. Frozen. Teammate D writes prompts against these names on hour 1 without waiting for C's implementation.

```python
search_logs(query: str, category: str|None, start: str, end: str, limit: int = 20) -> LogPage
check_ip(ip: str, window_hours: int = 24) -> IpProfile
get_user_activity(user: str, start: str, end: str) -> UserProfile
timeline_around(timestamp: str, minutes_before: int = 15, minutes_after: int = 15,
                host: str|None = None, ip: str|None = None) -> Timeline
validate_detection_rule(query: str, start: str, end: str) -> RuleValidation
```

Time args accept ISO-8601 **or** relative (`"now-24h"`). Teammate C normalizes; Gemma is bad at date math and will emit both.

**Every** return type carries this envelope — it's what makes "only pulls what it needs" *visible* to a judge:

```json
{
  "data": [...],
  "meta": {
    "hits_total": 1284,
    "returned": 20,
    "truncated": true,
    "fields_returned": ["@timestamp","source.ip","user.name"],
    "es_query": { "...": "the actual DSL, for the Query Mentor card" },
    "took_ms": 34
  }
}
```

`meta.es_query` is non-negotiable — it feeds the frontend's Query Mentor panel and is the single strongest piece of evidence for the "seamless NL→Elastic pipeline" criterion.

---

## 4. Rules that prevent the three classic failures

1. **Never return raw `_source` wholesale.** Every tool projects an explicit field list. This *is* the "only the specific data it needs" requirement — build it in, don't retrofit it.
2. **Strip `labels.*` before returning to the agent.** One line in Teammate C's projection. Forgetting it means Gemma reads the answer key and every result is worthless.
3. **Cap `limit` at 50 server-side.** A 12B model on a T4 drowns past ~8k tokens of JSON and the demo stalls live.

---

## 5. Transport decision (blocks Teammate A and C)

| If submission is | Transport | Consequence |
|---|---|---|
| GitHub repo + video | FastMCP over HTTP, separate process | Clean,真 multi-process MCP story |
| Kaggle notebook, no internet | FastMCP in-process (stdio) | Same tool code, different mount |

**Write tool functions as plain Python, then register with FastMCP.** Both transports then work from one implementation. Confirm which before hour 1 ends.

---

## 6. Hour-by-hour sync points

| Time | Sync | Gate |
|---|---|---|
| **T+0:30** | Contract frozen | Everyone has read this file |
| **T+1:30** | B publishes `secops-logs-*`; C's 5 tools return **stub** data matching §3 | A and D unblock on stubs |
| **T+2:30** | C swaps stubs → real Elastic. D's graph runs one full loop end-to-end | First real answer |
| **T+3:30** | **Feature freeze.** A wires final SSE; extras land or get cut | No new features after this |
| **T+4:00** | Demo rehearsal on the 5 scripted questions | Record video |

**Stub-first is the whole plan.** C ships fake-but-shaped responses at T+1:30 so A and D never idle.

---

## 7. The five demo questions (everything is judged on these)

1. "What IPs seem malicious today and why?" ← *the track's literal example, must be flawless*
2. "Did anyone log in from two countries at once?"
3. "Show me what happened around the vpn-gw-01 incident." ← time-travel
4. *[drops phishing screenshot]* "Did anyone click this?" ← multimodal
5. "Write me a detection rule for that brute-force pattern." ← Sigma forge

Teammate B seeds data so all five have a real, findable answer. Teammate D scripts the graph to handle exactly these shapes well.

---

## 8. Repo layout

```
/agent      → Teammate D   (LangGraph, prompts, Gemma client)
/mcp        → Teammate C   (FastMCP server, tool impls, ES client)
/data       → Teammate B   (generators, mappings, seed script)
/ui         → Teammate A   (frontend)
/plans      → these documents
```

One person per directory. Cross-directory edits go through the owner.
