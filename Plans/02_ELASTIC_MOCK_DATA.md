# Plan 02 — Elastic Mock Data · Teammate B

**Read `00_SHARED_CONTRACT.md` first.** You own §2 (the canonical document). Your schema is law for the other three.

**You are the critical path.** Nobody's work is real until your index exists. Your T+1:30 gate is the hardest deadline on the team.

---

## Why this role decides the demo

The judges' criterion is a *seamless NL→Elastic pipeline returning a reasoned threat assessment*. Gemma can only reason as well as your data lets it. If your logs are uniform noise, the agent says "nothing notable" and the demo dies. If your logs contain **planted, discoverable narratives**, the agent looks brilliant.

You are not generating data. You are **writing five detective stories in log form**, then burying them in realistic noise.

---

## Phase 1 (T+0:30 → T+1:00) — Ship the index empty but correct

Do this before generating a single realistic event. C and D need the *shape*.

**1. Mapping.** Explicit, not dynamic — dynamic mapping will type `source.ip` as `text` and every IP filter silently fails.

```python
MAPPING = {
  "properties": {
    "@timestamp": {"type": "date"},
    "event":   {"properties": {"category": {"type":"keyword"}, "action": {"type":"keyword"}, "outcome": {"type":"keyword"}}},
    "source":  {"properties": {"ip": {"type":"ip"},
                "geo": {"properties": {"country":{"type":"keyword"},"city":{"type":"keyword"},
                        "location":{"type":"geo_point"}}}}},
    "user":    {"properties": {"name": {"type":"keyword"}, "id": {"type":"keyword"}}},
    "host":    {"properties": {"name": {"type":"keyword"}, "ip": {"type":"ip"}}},
    "url":     {"properties": {"full": {"type":"keyword"}, "domain": {"type":"keyword"}}},
    "network": {"properties": {"bytes": {"type":"long"}, "direction": {"type":"keyword"}}},
    "process": {"properties": {"name": {"type":"keyword"}, "pid": {"type":"integer"}}},
    "message": {"type": "text"},
    "labels":  {"properties": {"scenario": {"type":"keyword"}, "is_threat": {"type":"boolean"}}}
  }
}
```

`source.ip` as `ip` type and `geo.location` as `geo_point` are the two that break things later if wrong.

**2. Decide Elastic runtime now.** Docker `elasticsearch:8.x` with `xpack.security.enabled=false` if the team has Docker; otherwise an in-memory shim exposing `.search()`. Tell C within 15 minutes — it changes their client code.

**3. Push 10 hand-written docs** covering all seven categories. Ping C: *"index live, 10 docs, mapping frozen."* C now builds against reality.

---

## Phase 2 (T+1:00 → T+2:00) — The five planted narratives

One generator function per demo question. Each writes a **causally coherent** event chain — that's what makes autonomous follow-up (Plan 04) actually work. The pivot must exist in the data or the agent's second hop finds nothing.

### Narrative 1 — Brute force → success → exfil (`labels.scenario: "bruteforce_then_success"`)
Answers demo Q1 *and* Q5. The centerpiece.

```
14:02–14:19  60 × authentication/login_failed, source.ip 45.133.1.88, user j.smith, host vpn-gw-01
14:21        1 × authentication/login_success,  SAME ip, SAME user          ← the pivot
14:26        1 × process/process_started, name "powershell.exe", host vpn-gw-01
14:31        3 × network/connection, direction outbound, bytes 4_200_000, dest 45.133.1.88
```

The chain rewards depth: `check_ip(45.133.1.88)` → sees the success → `get_user_activity(j.smith)` → finds the exfil. A shallow agent reports "60 failed logins." A good one reports **"compromise with data theft."** Same data, and the difference is entirely the agent's hops — build the chain so that difference is possible.

### Narrative 2 — Impossible travel (`"impossible_travel"`)
```
08:00 UTC  login_success, user a.patel, source.ip 73.42.x.x, geo US/Chicago,   host vpn-gw-01
08:14 UTC  login_success, user a.patel, source.ip 91.216.x.x, geo DE/Frankfurt, host aws-rds-prod
```
14 minutes, 7000 km. Make it *arithmetically* obvious — Gemma 12B reasons about "14 minutes, two continents" reliably but won't do haversine math. Include `geo.country` prominently.

### Narrative 3 — The vpn-gw-01 incident window (`"suspicious_service"`)
Built for `timeline_around()`. Pick anchor `T = 03:47:00Z`, then:
- `T-12m` → normal cron/process noise (proves the tool isn't just dumping everything)
- `T-4m`  → `file/file_created`, `/tmp/.hidden/update.sh`
- `T`     → `process/process_started`, `nc -lvp 4444` ← the smoking gun
- `T+3m`  → `network/listening_port_opened`, port 4444
- `T+9m`  → outbound connection to an external IP

Before/after asymmetry is the entire visual payoff of time-travel. Quiet before, loud after.

### Narrative 4 — Phishing click-through (`"phishing_click"`)
Must match the screenshot Teammate A/D prepare. **Coordinate the exact domain string — write it in this doc the moment it's chosen.**
```
domain: micros0ft-verify.co   (zero for 'o' — visually subtle, judges love catching it)
11:47  web/http_request, url.domain micros0ft-verify.co, user r.gupta,  outcome success
11:49  web/http_request, SAME domain,                    user t.nair,   outcome success
11:52  authentication/login_success, user r.gupta from a new ASN        ← credential replay
```
Two clickers, not one — "2 employees clicked" is a far better demo line than "1 employee clicked."

### Narrative 5 — Benign lookalikes (the false-positive trap)
**Do not skip this.** Plant volume that *looks* threatening and is not:
- A backup service, 400 outbound connections nightly, large bytes → benign
- A misconfigured health-checker, 200 auth failures from an **internal** IP, never succeeding → benign
- A load balancer producing correlated 5xx bursts → benign

This is what makes Q1 ("what IPs seem *malicious*, and **why**") a real test. Without traps, any agent that lists top-talker IPs scores full marks. With them, only an agent that reasons scores. It also gives `validate_detection_rule()` genuine false positives to measure, so the Sigma feature's 0%-FP claim means something.

---

## Phase 3 (T+2:00 → T+2:30) — Noise bed

~5,000 benign events over 48h, so the narratives are found by *reasoning*, not by being the only data present.

- **Diurnal curve** — heavy 09:00–18:00, sparse overnight. Flat-random timestamps read as fake instantly to a security-literate judge, and they break "today" queries.
- **~25 users** from a fixed roster, Zipf-distributed. Include `j.smith` **and** `john.smith` as distinct accounts — this is the planted trigger for self-healing's username-format retry (Plan 04). Without it that feature has nothing to recover from.
- **Internal IPs** `10.0.x.x`, a handful of repeat external IPs so `check_ip` has history.
- **Realistic `message` strings** — the text field is what makes a screenshot look authentic.

Seed the RNG. `random.seed(1337)`. A demo that changes between rehearsal and judging is a demo that breaks during judging.

---

## Phase 4 (T+2:30 → T+3:15) — Verify, then hand off

Write `verify.py` asserting **each of the five questions has a findable answer**:

```python
assert count(category="authentication", ip="45.133.1.88", outcome="failure") >= 55
assert count(category="authentication", ip="45.133.1.88", outcome="success") == 1
assert distinct_countries(user="a.patel", window="08:00-08:30") == {"US","DE"}
assert count(url_domain="micros0ft-verify.co") == 2
assert exists(process_name="nc", host="vpn-gw-01")
assert count(scenario="benign_backup") > 300   # traps present
```

Run it after every regeneration. This file is your contract with the other three — when D says "the agent found nothing," `verify.py` settles instantly whether it's your data or their prompt.

**Deliverables:** `/data/mapping.json`, `/data/generate.py`, `/data/seed.py`, `/data/verify.py`, and a `SCENARIOS.md` listing each narrative with its exact IPs, users, domains, and timestamps. **D and A cannot write prompts or demo scripts without those literal values** — publish `SCENARIOS.md` the moment Phase 2 ends, don't wait for Phase 4.

---

## Cuts if you fall behind

Narratives 1, 2, 4 → the noise bed → Narrative 3 → Narrative 5. Never cut 1. If forced, shrink noise to 1,000 events before dropping any narrative.
