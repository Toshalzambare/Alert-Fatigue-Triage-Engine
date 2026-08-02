"""
Database Viewer
================
Inspect the contents of the secops-logs index.
Shows index stats, scenario breakdown, user distribution, and sample docs.

Usage:
  python db/view_db.py                  # full overview
  python db/view_db.py --scenario bruteforce_then_success   # filter by scenario
  python db/view_db.py --user j.smith   # filter by user
  python db/view_db.py --samples 10     # show 10 sample docs (default: 5)
"""

import os
import sys
import json
import argparse
from elasticsearch import Elasticsearch
from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

INDEX = "secops-logs-2026.08.02"


def print_header(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_table(headers, rows):
    """Simple ASCII table printer."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
    print(f"  {fmt.format(*headers)}")
    print(f"  {fmt.format(*['-' * w for w in col_widths])}")
    for row in rows:
        print(f"  {fmt.format(*[str(c) for c in row])}")


def overview(es):
    """Show index stats and high-level counts."""
    print_header("INDEX OVERVIEW")

    count = es.count(index=INDEX)["count"]
    print(f"  Index:          {INDEX}")
    print(f"  Total docs:     {count}")


def scenario_breakdown(es):
    """Show counts per labels.scenario."""
    print_header("SCENARIO BREAKDOWN")

    result = es.search(index=INDEX, body={
        "size": 0,
        "aggs": {
            "scenarios": {
                "terms": {"field": "labels.scenario", "size": 20}
            }
        }
    })

    rows = []
    for bucket in result["aggregations"]["scenarios"]["buckets"]:
        name = bucket["key"]
        count = bucket["doc_count"]
        threat = "THREAT" if name not in ("noise", "benign_backup",
                                           "benign_healthcheck",
                                           "benign_lb_burst",
                                           "realtime_noise") else "benign"
        rows.append((name, count, threat))

    rows.sort(key=lambda r: r[1], reverse=True)
    print_table(["Scenario", "Count", "Type"], rows)


def user_breakdown(es):
    """Show counts per user.name."""
    print_header("USER DISTRIBUTION (top 15)")

    result = es.search(index=INDEX, body={
        "size": 0,
        "aggs": {
            "users": {
                "terms": {"field": "user.name", "size": 15}
            }
        }
    })

    rows = []
    for bucket in result["aggregations"]["users"]["buckets"]:
        rows.append((bucket["key"], bucket["doc_count"]))

    print_table(["User", "Events"], rows)


def category_breakdown(es):
    """Show counts per event.category."""
    print_header("EVENT CATEGORIES")

    result = es.search(index=INDEX, body={
        "size": 0,
        "aggs": {
            "cats": {
                "terms": {"field": "event.category", "size": 10}
            }
        }
    })

    rows = []
    for bucket in result["aggregations"]["cats"]["buckets"]:
        rows.append((bucket["key"], bucket["doc_count"]))

    print_table(["Category", "Count"], rows)


def ip_breakdown(es):
    """Show top source IPs."""
    print_header("TOP SOURCE IPs")

    result = es.search(index=INDEX, body={
        "size": 0,
        "aggs": {
            "ips": {
                "terms": {"field": "source.ip", "size": 10}
            }
        }
    })

    rows = []
    for bucket in result["aggregations"]["ips"]["buckets"]:
        rows.append((bucket["key"], bucket["doc_count"]))

    print_table(["Source IP", "Events"], rows)


def sample_docs(es, count=5, scenario=None, user=None):
    """Show sample documents, optionally filtered."""
    filters = []
    title = f"SAMPLE DOCUMENTS (latest {count})"

    if scenario:
        filters.append({"term": {"labels.scenario": scenario}})
        title += f" [scenario={scenario}]"
    if user:
        filters.append({"term": {"user.name": user}})
        title += f" [user={user}]"

    print_header(title)

    query = {"match_all": {}}
    if filters:
        query = {"bool": {"filter": filters}}

    result = es.search(index=INDEX, body={
        "query": query,
        "sort": [{"@timestamp": "desc"}],
        "size": count,
        "_source": ["@timestamp", "event.category", "event.action",
                     "event.outcome", "source.ip", "source.geo.country",
                     "user.name", "host.name", "process.name",
                     "url.domain", "network.bytes", "message",
                     "labels.scenario", "labels.is_threat"],
    })

    hits = result["hits"]["hits"]
    if not hits:
        print("  No documents found matching the filter.")
        return

    for i, hit in enumerate(hits):
        src = hit["_source"]
        print(f"\n  --- Doc {i + 1} ---")
        print(f"  @timestamp:  {src.get('@timestamp')}")
        print(f"  event:       {src.get('event', {}).get('category')}"
              f" / {src.get('event', {}).get('action')}"
              f" / {src.get('event', {}).get('outcome')}")

        if src.get("source", {}).get("ip"):
            geo = src.get("source", {}).get("geo", {}).get("country", "")
            geo_str = f" ({geo})" if geo else ""
            print(f"  source.ip:   {src['source']['ip']}{geo_str}")

        if src.get("user", {}).get("name"):
            print(f"  user:        {src['user']['name']}")
        if src.get("host", {}).get("name"):
            print(f"  host:        {src['host']['name']}")
        if src.get("process", {}).get("name"):
            print(f"  process:     {src['process']['name']}")
        if src.get("url", {}).get("domain"):
            print(f"  url.domain:  {src['url']['domain']}")
        if src.get("network", {}).get("bytes"):
            print(f"  net.bytes:   {src['network']['bytes']}")

        msg = src.get("message", "")
        if msg:
            print(f"  message:     {msg[:100]}")

        labels = src.get("labels", {})
        print(f"  scenario:    {labels.get('scenario')}"
              f"  |  is_threat: {labels.get('is_threat')}")


def main():
    parser = argparse.ArgumentParser(description="Inspect the secops-logs Elastic index")
    parser.add_argument("--scenario", type=str, default=None,
                        help="Filter samples by labels.scenario")
    parser.add_argument("--user", type=str, default=None,
                        help="Filter samples by user.name")
    parser.add_argument("--samples", type=int, default=5,
                        help="Number of sample documents to show (default: 5)")
    args = parser.parse_args()

    es = Elasticsearch(
        os.getenv("ELASTIC_URL"),
        api_key=os.getenv("ELASTIC_API_KEY"),
    )

    if not es.indices.exists(index=INDEX):
        print(f"[ERR] Index '{INDEX}' does not exist. Run generate_mock_data.py first.")
        sys.exit(1)

    overview(es)
    scenario_breakdown(es)
    category_breakdown(es)
    user_breakdown(es)
    ip_breakdown(es)
    sample_docs(es, count=args.samples, scenario=args.scenario, user=args.user)

    print(f"\n{'=' * 60}")
    print("  Done.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
