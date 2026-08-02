# Plan 03 — FastMCP Integration · Teammate C

**Read `00_SHARED_CONTRACT.md` first.** You own §3 and §4.

**Your work is the single most rubric-aligned deliverable on the team.** The track says: *"Strong submissions will utilize Gemma 4's native function calling—and ideally the Model Context Protocol (MCP)—to standardize the connection to Elastic and ensure the agent only pulls the specific data it needs."*

That sentence is your job description. Two judgeable claims live in your code:
1. **MCP standardizes the Elastic connection** → clean tool boundary, no raw DSL in the agent.
2. **Only the specific data it needs** → field projection + `meta` envelope, provable per call.

Build #2 as a *visible* feature, not an implementation detail. A judge can't see efficiency unless you show it.

---

## Phase 0 (T+0:30 → T+0:45) — Two decisions, then tell everyone

**Transport** (contract §5): HTTP if the submission is a repo, stdio if it's an offline notebook. Structure so it doesn't matter:

```python
# tools/impl.py — plain Python. Testable, no MCP import.
def _search_logs(query, category, start, end, limit=20) -> dict: ...

# server.py — thin registration layer
mcp = FastMCP("secops-elastic")
mcp.tool()(search_logs)   # wraps _search_logs
```

Never put logic in the decorated function. You'll want to unit-test without a server, and if transport flips at hour 3 you change one file.

**Elastic client** — confirm with B whether it's Docker or in-memory shim. Wrap it behind `es.search(index, body)` either way so a swap is one class.

---

## Phase 1 (T+0:45 → T+1:30) — STUBS FIRST ⚠️

**This is the highest-leverage 45 minutes anyone on the team spends.**

Ship all five tools returning **hardcoded, correctly-shaped** responses. No Elastic. Just the contract §3 envelope with plausible values drawn from B's `SCENARIOS.md`.

```python
def _check_ip(ip: str, window_hours: int = 24) -> dict:
    return {
      "data": {"ip": ip, "total_events": 64, "first_seen": "2026-08-02T14:02:11Z",
               "last_seen": "2026-08-02T14:31:02Z", "countries": ["DE"],
               "users_targeted": ["j.smith"], "categories": {"authentication": 61, "network": 3},
               "failed_logins": 60, "successful_logins": 1},
      "meta": {"hits_total": 64, "returned": 64, "truncated": False,
               "fields_returned": ["source.ip","user.name","event.action"],
               "es_query": {"query": {"bool": {"filter": [{"term": {"source.ip": ip}}]}}},
               "took_ms": 12}
    }
```

Announce at T+1:30: *"all five tools live, stub data, contract-shaped."* **D can now build the entire LangGraph and A can build the entire UI against a real MCP server while you write ES queries.** Skipping this step serializes three people behind you and is the most likely way this project fails.

---

## Phase 2 (T+1:30 → T+2:45) — Real queries, in priority order

### `search_logs` — the workhorse (build first, hardest)
Gemma emits a *natural-language-ish* `query` string. Do **not** ask it for raw ES DSL — a 12B model produces syntactically-invalid DSL often enough to wreck a live demo. Translate deterministically in Python:

```python
must = []
if category: must.append({"term": {"event.category": category}})
if ip_in(query):    must.append({"term": {"source.ip": extract_ip(query)}})
if user_in(query):  must.append({"term": {"user.name": extract_user(query)}})
if free_text(query):must.append({"match": {"message": free_text(query)}})
must.append({"range": {"@timestamp": {"gte": norm(start), "lte": norm(end)}}})
```

Regex-extract IPs/users/domains from the query string, structured-filter those, `match` the remainder. Precise *and* forgiving.

**Field projection — the rubric line.** Never `_source: true`:
```python
"_source": ["@timestamp","event.category","event.action","event.outcome",
            "source.ip","source.geo.country","user.name","host.name",
            "url.domain","network.bytes","process.name","message"]
```
Note what's absent: `labels.*`. Contract §4 rule 2 — **strip the answer key.** Assert it in a test; forgetting it invalidates every result.

**Time normalization.** Accept `"now-24h"`, `"today"`, ISO-8601, and `"2026-08-02"`. Gemma emits all four. One `norm()` helper, and never let a bad date string reach ES — default to `now-24h` and set `meta.time_defaulted: true` so D's self-healing can react.

### `check_ip` — pure aggregation, zero raw docs
The clearest "only what it needs" demo: 64 documents collapse to one ~200-token profile. Terms aggs on country/user/category + a `filters` agg splitting success vs failure. **Return no raw hits at all.** Say so in your README — it's a strong, specific efficiency claim.

### `get_user_activity`
Aggregations by category and by source country, plus the 5 most recent notable events. Include `distinct_countries` as a top-level field — it hands the impossible-travel answer to Gemma without asking it to compute geography.

### `timeline_around` — powers time-travel
Two queries (before/after the anchor) or one range query bucketed in Python. Return events **grouped and ordered** with an explicit `"phase": "before" | "after"` on each. A pre-shaped payload means Gemma just narrates rather than sorting, and A renders it directly.
```json
{"anchor": "...", "before": [...], "after": [...],
 "summary": {"before_count": 3, "after_count": 9, "new_categories_after": ["process","network"]}}
```
`new_categories_after` is the insight the demo needs — hand it over computed.

### `validate_detection_rule` — powers Sigma forge
Takes a query, runs it over history, returns match count **and** — using B's `labels.scenario`, the one place you legitimately read the answer key — a true/false-positive split:
```json
{"matches": 61, "true_positives": 60, "false_positives": 1, "fp_rate": 0.016,
 "sample_fps": [{"...": "..."}]}
```
This is what turns "I wrote a rule" into "I wrote a rule and **proved** it's 1.6% FP against 48h of history." Read `labels` here and only here — never leak it through the other four tools.

---

## Phase 3 (T+2:45 → T+3:30) — Hardening for a live demo

1. **Never raise into the agent.** Any exception → `{"data": [], "meta": {"error": "...", "hits_total": 0}}`. An MCP exception can kill D's graph mid-demo; an empty result triggers self-healing and *looks intentional*.
2. **Enforce `limit ≤ 50`** server-side, and set `meta.truncated`. Contract §4 rule 3.
3. **Log every call** to `/mcp/calls.jsonl` — tool, args, hits, ms. A "12 tool calls, 340ms total" stat in the writeup is cheap and concrete.
4. **Rich tool docstrings.** FastMCP sends these to Gemma as the function-calling schema, so **your docstrings are D's prompt engineering.** Spell out the closed `category` set and give an example call in each. When D says "Gemma picks the wrong tool," fix it here first — it's usually faster than changing the system prompt.

---

## Deliverables

`/mcp/server.py`, `/mcp/tools/impl.py`, `/mcp/es_client.py`, `/mcp/test_tools.py`, and a README documenting the five tools + the efficiency claim (aggregations over raw hits, explicit projection, capped limits, per-call `meta`).

**Cut order if behind:** `validate_detection_rule` → `timeline_around` → `get_user_activity`. `search_logs` and `check_ip` are the track's literal demo question — they ship no matter what.
