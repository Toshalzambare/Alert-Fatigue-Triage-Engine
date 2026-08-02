# Plan 01 — Frontend · Teammate A

**Read `00_SHARED_CONTRACT.md` first.**

**Your job is not "a chat UI." It is making invisible agent reasoning visible to a judge in 90 seconds.**

Teammate D's autonomous hops, self-healing retries, and field-projection efficiency all happen inside Python. If you render only a final answer paragraph, the judges see a chatbot and the team's best work scores zero. **Every claim in the writeup needs a pixel on screen.**

---

## Stack decision (T+0:30, 10 minutes)

**Recommendation: Streamlit.** Ugly-but-shipped beats beautiful-but-broken at hour 4, it's one process, and it renders images/JSON natively.

Take React + FastAPI/SSE **only** if you're genuinely fast with it — the streaming trace looks better, but you're spending an hour on plumbing that Streamlit gives free.

Either way build against **fake JSON files first**. Write `mock_events.jsonl` matching contract §1 event shapes, render the whole UI from it, and swap to the live agent at T+2:30. Never idle on D.

---

## The event stream (your contract with D)

D emits these as the graph runs. Render each distinctly:

```json
{"type":"triage",      "intent":"threat_hunt", "entities":{"time":"today"}}
{"type":"tool_call",   "tool":"search_logs", "args":{...}, "hop":1}
{"type":"tool_result", "meta":{"hits_total":1284,"returned":20,"fields_returned":[...],
                               "es_query":{...},"took_ms":34}}
{"type":"agent_hop",   "from":"search_logs","to":"check_ip","reason":"IP 45.133.1.88 had 60 failures"}
{"type":"healing",     "attempt":1,"fix":"username_format","from":"j.smith","to":"john.smith"}
{"type":"injection",   "neutralized":true,"pattern":"ignore previous instructions"}
{"type":"token",       "text":"..."}
{"type":"verdict",     "severity":"high","summary":"...","iocs":[...]}
```

Agree this list with D at T+0:30 and don't renegotiate it after T+2:00.

---

## Layout — two panes, and the right pane is the point

```
┌───────────────────────────────┬──────────────────────────────┐
│  ANALYST CHAT                 │  AGENT REASONING TRACE       │
│                               │                              │
│  > What IPs seem malicious    │  ▸ TRIAGE  intent=threat_hunt│
│    today and why?             │                              │
│                               │  ┌ HOP 1 ─────────────────┐  │
│  [🖼 drop screenshot]         │  │ 🔧 search_logs          │  │
│                               │  │ 1284 hits → 20 returned │  │
│  ┌─ VERDICT ─────────────┐    │  │ 12 fields  ·  34ms      │  │
│  │ 🔴 HIGH               │    │  │ [ view ES query ]       │  │
│  │ 45.133.1.88 —         │    │  └────────────────────────┘  │
│  │ brute force → success │    │       ↓ found IP w/ 60 fails │
│  │ → 4.2MB exfil         │    │  ┌ HOP 2 ─────────────────┐  │
│  │                       │    │  │ 🔧 check_ip             │  │
│  │ IOCs: 45.133.1.88     │    │  │ 64 events → 1 profile   │  │
│  │ [Inspect Timeline]    │    │  │ 0 raw docs · agg only   │  │
│  │ [Forge Sigma Rule]    │    │  └────────────────────────┘  │
│  └───────────────────────┘    │                              │
└───────────────────────────────┴──────────────────────────────┘
```

**The right pane is your highest-value work.** Build it before you polish anything on the left.

---

## The five things that must be visible

### 1. Hop cards with reasons
Each hop is a card that **appears in sequence** (don't batch-render at the end — the sequence *is* the demo). The connector text `↓ found IP with 60 failures` between cards is what proves autonomy: the agent chose the next step and said why.

### 2. The efficiency line — your rubric moment
On every tool card: **`1284 hits → 20 returned · 12 fields · 34ms`**

This is the visual proof of *"only pulls the specific data it needs."* It's one line of text and it's the highest score-per-pixel element in the whole UI. On `check_ip`, show **`64 events → 1 profile · 0 raw documents`**.

### 3. Query Mentor card (from `meta.es_query`)
A collapsible **[view ES query]** on each tool card showing the real DSL. Expanded, it directly evidences "seamless NL→Elastic pipeline." If time permits, add D's one-line explanation of *why* those filters — that's the Educational Query Mentor feature from the ideas doc, nearly free since C already returns the query.

### 4. Self-healing chain
Render retries as an **amber** sub-card under the failed call:
```
⚠ 0 results
   ↻ retry 1 — username format: j.smith → john.smith
   ✓ 47 results
```
Amber, not red. Red reads as *broken*; amber reads as *recovering*. That distinction is the entire feature.

### 5. Injection banner
On `{"type":"injection"}`, a small red bar: **⚠️ Prompt injection in log data — neutralized.** 15 seconds of demo, near-zero build cost.

---

## Multimodal upload (coordinate with D)

`st.file_uploader` → show the thumbnail inline → post bytes to the agent. While vision runs, render an **extraction card**:
```
🖼 VISION ANALYSIS
   brand impersonated:  Microsoft 365
   extracted domain:    micros0ft-verify.co   ⚠ typosquat (0 for o)
   red flags: urgency banner, mismatched sender
   ↓ searching logs for this domain
```
The `↓ searching logs` line is essential — it shows vision feeding the *same* pipeline rather than being a bolt-on. Prepare the screenshot yourself: a fake M365 login page with a visible typosquatted URL bar. Make the flaw **legible at video resolution**; subtle-but-invisible scores nothing.

---

## Timeline view (the *Inspect Timeline* button)

From the verdict card, POST `{anchor, host}` to D — no NL round-trip. Render two stacked columns:

```
BEFORE (15m)              │  AFTER (15m)
03:35  cron job           │  03:47  ⚠ process: nc -lvp 4444
03:41  routine auth       │  03:50  ⚠ port 4444 listening
                          │  03:56  ⚠ outbound → 45.133.1.88
   quiet                  │     3 new categories
```

Quiet-left / loud-right asymmetry is the whole payoff. Color the after-column red and add the `new_categories_after` count from C's `summary`.

---

## Timeline

| Time | Deliverable |
|---|---|
| T+0:30 | Stack chosen; event list agreed with D; `mock_events.jsonl` written |
| T+1:30 | Full UI rendering from mocks — chat, trace pane, hop cards, verdict |
| T+2:30 | Wired to live agent; upload path working |
| T+3:30 | **Freeze.** Timeline view + injection banner + polish only |
| T+4:00 | Demo rehearsal; 1280×720; font size ≥16px |

---

## Polish that actually pays (last 20 minutes only)

- **Dark theme** — security tooling looks wrong in light mode. `#0d1117` bg, `#58a6ff` accents. One config block.
- **Severity color** — red/amber/green on the verdict badge only. Don't rainbow the UI.
- **Monospace for IPs, users, domains.** Signals "security tool" instantly.
- **Fixed-height trace pane, auto-scroll.** Prevents layout jump mid-demo.

Skip: animations, custom fonts, responsive breakpoints, a settings page. None are judged.

**Cut order:** timeline view → injection banner → Query Mentor → hop cards. Never cut hop cards or the efficiency line — they carry the two rubric claims.
