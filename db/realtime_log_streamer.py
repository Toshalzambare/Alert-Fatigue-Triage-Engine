"""
Real-Time Log Streamer
=======================
Generates and pushes new security log events to Elastic at regular intervals.
Simulates live SOC activity for demo purposes.

Usage:
  python db/realtime_log_streamer.py                # default 5s interval
  python db/realtime_log_streamer.py --interval 2   # every 2 seconds
  python db/realtime_log_streamer.py --interval 0.5  # rapid fire
"""

import os
import sys
import time
import random
import argparse
from datetime import datetime, timezone
from elasticsearch import Elasticsearch
from dotenv import load_dotenv

# ── Load .env from project root ─────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

INDEX = "secops-logs-2026.08.02"

# ── User & Host Rosters ─────────────────────────────────────────

USERS = [
    ("m.chen",      "u-1001"), ("s.kumar",     "u-1002"),
    ("l.johnson",   "u-1003"), ("p.williams",  "u-1004"),
    ("k.lee",       "u-1005"), ("d.garcia",    "u-1006"),
    ("n.martinez",  "u-1007"), ("b.anderson",  "u-1008"),
    ("c.thomas",    "u-1009"), ("e.jackson",   "u-1010"),
    ("f.white",     "u-1011"), ("g.harris",    "u-1012"),
    ("h.martin",    "u-1013"), ("j.smith",     "u-1042"),
    ("a.patel",     "u-2017"), ("r.gupta",     "u-3005"),
]

HOSTS = [
    ("ws-PC-045", "10.0.1.45"), ("ws-PC-078", "10.0.1.78"),
    ("file-srv-01", "10.0.5.10"), ("dc-01", "10.0.0.1"),
    ("mail-gw-01", "10.0.6.20"), ("vpn-gw-01", "10.0.4.12"),
]

# Event types with relative weights
EVENTS = [
    # (category, action, outcome, weight, is_suspicious)
    ("authentication", "login_success",   "success", 35, False),
    ("authentication", "login_failed",    "failure", 5,  True),
    ("web",            "http_request",    "success", 25, False),
    ("process",        "process_started", "success", 15, False),
    ("dns",            "dns_query",       "success", 10, False),
    ("file",           "file_accessed",   "success", 8,  False),
    ("network",        "connection",      "success", 2,  False),
]

MESSAGES = {
    ("authentication", "login_success"): [
        "Successful login for {user} from {ip} via Kerberos",
        "SSO session established for {user} from {ip}",
        "Password authentication successful for {user} from {ip}",
        "Session renewed for {user} - token refresh successful",
    ],
    ("authentication", "login_failed"): [
        "Failed password for {user} from {ip} port {port}",
        "Authentication failure for {user} from {ip} - invalid credentials",
        "Login denied for {user} from {ip} - account locked after 3 attempts",
    ],
    ("web", "http_request"): [
        "HTTP GET /api/v2/status 200 OK ({bytes} bytes)",
        "HTTP POST /api/v2/data 201 Created ({bytes} bytes)",
        "HTTP GET /dashboard/analytics 200 OK ({bytes} bytes)",
        "HTTP GET /api/v1/health 200 OK ({bytes} bytes)",
    ],
    ("process", "process_started"): [
        "Process started: chrome.exe by {user} on {host}",
        "Process started: outlook.exe by {user} on {host}",
        "Process started: teams.exe by {user} on {host}",
        "Process started: code.exe by {user} on {host}",
        "Process started: excel.exe by {user} on {host}",
    ],
    ("dns", "dns_query"): [
        "DNS query: {user} resolved mail.company.internal",
        "DNS query: {user} resolved sharepoint.company.internal",
        "DNS query: {user} resolved vpn.company.internal",
        "DNS query: {user} resolved api.company.internal",
    ],
    ("file", "file_accessed"): [
        "File accessed: /shared/reports/weekly_report.xlsx by {user}",
        "File accessed: /home/{user}/documents/notes.docx",
        "File read: /shared/policies/security_v3.pdf by {user}",
    ],
    ("network", "connection"): [
        "Outbound connection from {host} to 142.250.80.46:443 ({bytes} bytes)",
        "Outbound connection from {host} to 104.18.32.7:443 ({bytes} bytes)",
    ],
}

PROCS = ["chrome.exe", "outlook.exe", "teams.exe", "code.exe",
         "excel.exe", "notepad.exe", "explorer.exe"]


def generate_event():
    """Generate a single random security log event with the current timestamp."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    # Pick event type (weighted)
    categories = [e[0] for e in EVENTS]
    actions    = [e[1] for e in EVENTS]
    outcomes   = [e[2] for e in EVENTS]
    weights    = [e[3] for e in EVENTS]

    idx = random.choices(range(len(EVENTS)), weights=weights, k=1)[0]
    category, action, outcome = categories[idx], actions[idx], outcomes[idx]
    is_suspicious = EVENTS[idx][4]

    # Pick user and host
    user_name, user_id = random.choice(USERS)
    host_name, host_ip = random.choice(HOSTS)
    src_ip = f"10.0.1.{random.randint(10, 99)}"

    # Optional fields
    net_bytes = random.randint(500, 80000) if category in ("web", "network") else None
    net_dir   = "outbound" if category in ("web", "network") else None
    proc      = random.choice(PROCS) if category == "process" else None
    pid       = random.randint(1000, 9999) if category == "process" else None
    port      = random.randint(40000, 65000)

    # If suspicious auth failure, occasionally use an external IP
    if is_suspicious and random.random() < 0.3:
        src_ip = f"{random.randint(60, 200)}.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}"

    # Message
    key = (category, action)
    templates = MESSAGES.get(key, ["Event: {category}/{action} by {user}"])
    msg = random.choice(templates).format(
        user=user_name, ip=src_ip, host=host_name,
        port=port, bytes=net_bytes or random.randint(500, 50000),
        category=category, action=action,
    )

    # Build geo (None for internal IPs)
    geo_loc = None
    geo_country = None
    geo_city = None
    if not src_ip.startswith("10."):
        geo_country = random.choice(["US", "DE", "GB", "JP", "IN"])
        geo_city = "Unknown"

    return {
        "@timestamp": now,
        "event":   {"category": category, "action": action, "outcome": outcome},
        "source":  {"ip": src_ip, "geo": {"country": geo_country, "city": geo_city, "location": geo_loc}},
        "user":    {"name": user_name, "id": user_id},
        "host":    {"name": host_name, "ip": host_ip},
        "url":     {"full": None, "domain": None},
        "network": {"bytes": net_bytes, "direction": net_dir},
        "process": {"name": proc, "pid": pid},
        "message": msg,
        "labels":  {"scenario": "realtime_noise", "is_threat": False},
    }


def main():
    parser = argparse.ArgumentParser(
        description="Stream security log events to Elastic in real-time"
    )
    parser.add_argument(
        "--interval", type=float, default=5.0,
        help="Seconds between events (default: 5.0)"
    )
    args = parser.parse_args()

    es = Elasticsearch(
        os.getenv("ELASTIC_URL"),
        api_key=os.getenv("ELASTIC_API_KEY"),
    )

    # Verify index exists
    if not es.indices.exists(index=INDEX):
        print(f"[ERR] Index '{INDEX}' does not exist. Run generate_mock_data.py first.")
        sys.exit(1)

    print(f"[LIVE] Streaming events every {args.interval}s to '{INDEX}'")
    print(f"   Press Ctrl+C to stop.\n")

    count = 0
    try:
        while True:
            event = generate_event()
            es.index(index=INDEX, document=event)
            count += 1

            cat  = event["event"]["category"]
            act  = event["event"]["action"]
            user = event["user"]["name"]
            msg  = event["message"][:75]
            print(f"  [{count:>4}] {cat}/{act:<20} | {user:<14} | {msg}")

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print(f"\n\n[STOP] Stopped. Streamed {count} events total.")


if __name__ == "__main__":
    main()
