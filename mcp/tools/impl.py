import re
import time
import json
from datetime import datetime, timedelta, timezone

from es_client import es_client, SAFE_FIELDS

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _normalize_time(t: str) -> str:
    if not t:
        return "now-24h"
    if t.startswith("now"):
        if t == "now/d":
            return t
        if t == "today":
            return "now/d"
        return t
    if t == "today":
        return "now/d"
    # ISO-8601 or bare date fallback
    try:
        # Check if it parses, if so, just pass through to ES which handles it well
        # ES accepts 2026-08-02, 2026-08-02T14:00:00Z, etc.
        return t
    except Exception:
        return "now-24h"

def _flatten(doc: dict, parent_key: str = '', sep: str = '.') -> dict:
    """Flatten nested dicts (e.g. event: {category: x} -> event.category: x)"""
    items = []
    for k, v in doc.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)

def _envelope(data, meta_kwargs) -> dict:
    """Construct standard response envelope."""
    meta = {
        "hits_total": 0,
        "returned": 0,
        "truncated": False,
        "fields_returned": SAFE_FIELDS,
        "es_query": {},
        "took_ms": 0
    }
    meta.update(meta_kwargs)
    return {"data": data, "meta": meta}

def _error(msg: str) -> dict:
    return _envelope([], {"error": msg})

# -----------------------------------------------------------------------------
# 1. search_logs
# -----------------------------------------------------------------------------

def search_logs(query: str, category: str = None, start: str = "now-24h", end: str = "now", limit: int = 20) -> dict:
    t0 = time.time()
    try:
        limit = min(limit, 50)
        must = []
        
        # 1. Category
        if category:
            must.append({"term": {"event.category": category}})
            
        # 2. Extract IPs
        ips = re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', query)
        for ip in ips:
            must.append({"term": {"source.ip": ip}})
            
        # 3. Extract Domains
        domains = re.findall(r'\b[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.[a-z]{2,}\b', query)
        for d in domains:
            if d not in ips and d not in ("login.failed", "login.success"):
                must.append({"term": {"url.domain": d}})
                query = query.replace(d, "") # prevent substring matches for users
                
        # 4. Extract Usernames
        users = re.findall(r'\b[a-z][a-z0-9]*[._-][a-z][a-z0-9]*\b', query)
        for u in users:
            if u not in ("login.failed", "login.success"): # skip common dot-words
                must.append({"term": {"user.name": u}})
                
        # 5. Extract Hosts
        known_hosts = {"vpn-gw-01", "dc-01", "ws-PC-045", "ws-PC-078", "file-srv-01", "mail-gw-01", "backup-srv-01", "lb-prod-01"}
        for h in known_hosts:
            if h in query:
                must.append({"term": {"host.name": h}})
                
        # 6. Remaining free text
        # Simple extraction: strip out IPs and known users/domains to leave raw text
        raw_text = query
        for e in ips + users + domains + list(known_hosts):
            raw_text = raw_text.replace(e, "")
        raw_text = raw_text.strip()
        if raw_text and len(raw_text) > 3:
            must.append({"match": {"message": raw_text}})
            
        # 7. Time range
        must.append({"range": {"@timestamp": {"gte": _normalize_time(start), "lte": _normalize_time(end)}}})
        
        body = {
            "query": {"bool": {"filter": must}},
            "size": limit,
            "sort": [{"@timestamp": "desc"}]
        }
        
        res = es_client.search(body)
        
        hits = res["hits"]["hits"]
        total = res["hits"]["total"]["value"]
        
        data = [_flatten(h["_source"]) for h in hits]
        
        return _envelope(data, {
            "hits_total": total,
            "returned": len(data),
            "truncated": total > len(data),
            "es_query": body,
            "took_ms": int((time.time() - t0) * 1000)
        })
    except Exception as e:
        return _error(str(e))

# -----------------------------------------------------------------------------
# 2. check_ip
# -----------------------------------------------------------------------------

def check_ip(ip: str, window_hours: int = 24) -> dict:
    t0 = time.time()
    try:
        body = {
            "query": {"bool": {"filter": [
                {"term": {"source.ip": ip}},
                {"range": {"@timestamp": {"gte": f"now-{window_hours}h"}}}
            ]}},
            "size": 0,
            "aggs": {
                "by_country": {"terms": {"field": "source.geo.country", "size": 10}},
                "by_user": {"terms": {"field": "user.name", "size": 10}},
                "by_category": {"terms": {"field": "event.category", "size": 10}},
                "by_outcome": {"terms": {"field": "event.outcome", "size": 10}},
                "first_seen": {"min": {"field": "@timestamp"}},
                "last_seen": {"max": {"field": "@timestamp"}},
            }
        }
        
        res = es_client.search(body)
        aggs = res.get("aggregations", {})
        total = res["hits"]["total"]["value"]
        
        data = {
            "ip": ip,
            "total_events": total,
            "first_seen": aggs.get("first_seen", {}).get("value_as_string"),
            "last_seen": aggs.get("last_seen", {}).get("value_as_string"),
            "countries": [b["key"] for b in aggs.get("by_country", {}).get("buckets", [])],
            "users_targeted": [b["key"] for b in aggs.get("by_user", {}).get("buckets", [])],
            "categories": {b["key"]: b["doc_count"] for b in aggs.get("by_category", {}).get("buckets", [])},
            "failed_logins": next((b["doc_count"] for b in aggs.get("by_outcome", {}).get("buckets", []) if b["key"] == "failure"), 0),
            "successful_logins": next((b["doc_count"] for b in aggs.get("by_outcome", {}).get("buckets", []) if b["key"] == "success"), 0),
        }
        
        return _envelope(data, {
            "hits_total": total,
            "returned": total,
            "truncated": False,
            "fields_returned": ["source.ip", "user.name", "event.action"], # specific fields we logically fetched
            "es_query": body,
            "took_ms": int((time.time() - t0) * 1000)
        })
    except Exception as e:
        return _error(str(e))

# -----------------------------------------------------------------------------
# 3. get_user_activity
# -----------------------------------------------------------------------------

def get_user_activity(user: str, start: str = "now-24h", end: str = "now") -> dict:
    t0 = time.time()
    try:
        body = {
            "query": {"bool": {"filter": [
                {"term": {"user.name": user}},
                {"range": {"@timestamp": {"gte": _normalize_time(start), "lte": _normalize_time(end)}}}
            ]}},
            "size": 0,
            "aggs": {
                "by_category": {"terms": {"field": "event.category", "size": 10}},
                "by_country": {"terms": {"field": "source.geo.country", "size": 10}},
                "distinct_ips": {"cardinality": {"field": "source.ip"}},
                "notable": {
                    "filter": {"terms": {"event.category": ["process", "network", "file"]}},
                    "aggs": {
                        "recent": {
                            "top_hits": {
                                "_source": SAFE_FIELDS,
                                "size": 5,
                                "sort": [{"@timestamp": "desc"}]
                            }
                        }
                    }
                }
            }
        }
        
        res = es_client.search(body)
        aggs = res.get("aggregations", {})
        total = res["hits"]["total"]["value"]
        
        notable_hits = aggs.get("notable", {}).get("recent", {}).get("hits", {}).get("hits", [])
        notable_events = [_flatten(h["_source"]) for h in notable_hits]
        
        data = {
            "user": user,
            "total_events": total,
            "distinct_countries": [b["key"] for b in aggs.get("by_country", {}).get("buckets", [])],
            "categories": {b["key"]: b["doc_count"] for b in aggs.get("by_category", {}).get("buckets", [])},
            "source_ips_count": aggs.get("distinct_ips", {}).get("value", 0),
            "notable": notable_events
        }
        
        return _envelope(data, {
            "hits_total": total,
            "returned": len(notable_events),
            "truncated": False,
            "es_query": body,
            "took_ms": int((time.time() - t0) * 1000)
        })
    except Exception as e:
        return _error(str(e))

# -----------------------------------------------------------------------------
# 4. timeline_around
# -----------------------------------------------------------------------------

def timeline_around(timestamp: str = None, anchor: str = None, minutes_before: int = 15, minutes_after: int = 15, host: str = None, ip: str = None) -> dict:
    t0 = time.time()
    try:
        anchor_ts = timestamp or anchor
        if not anchor_ts:
            return _error("Must provide timestamp or anchor")
            
        anchor_dt = datetime.fromisoformat(anchor_ts.replace("Z", "+00:00"))
        gte = (anchor_dt - timedelta(minutes=minutes_before)).isoformat()
        lte = (anchor_dt + timedelta(minutes=minutes_after)).isoformat()
        
        must = [{"range": {"@timestamp": {"gte": gte, "lte": lte}}}]
        if host:
            must.append({"term": {"host.name": host}})
        if ip:
            must.append({"term": {"source.ip": ip}})
            
        body = {
            "query": {"bool": {"filter": must}},
            "size": 50,
            "sort": [{"@timestamp": "asc"}]
        }
        
        res = es_client.search(body)
        hits = res["hits"]["hits"]
        total = res["hits"]["total"]["value"]
        
        before = []
        after = []
        before_cats = set()
        after_cats = set()
        
        for h in hits:
            flat = _flatten(h["_source"])
            dt = datetime.fromisoformat(flat["@timestamp"].replace("Z", "+00:00"))
            cat = flat.get("event.category")
            if dt < anchor_dt:
                flat["phase"] = "before"
                before.append(flat)
                if cat: before_cats.add(cat)
            else:
                flat["phase"] = "after"
                after.append(flat)
                if cat: after_cats.add(cat)
                
        new_cats = list(after_cats - before_cats)
        
        data = {
            "anchor": anchor_ts,
            "host": host,
            "ip": ip,
            "before": before,
            "after": after,
            "summary": {
                "before_count": len(before),
                "after_count": len(after),
                "new_categories_after": new_cats
            }
        }
        
        return _envelope(data, {
            "hits_total": total,
            "returned": len(before) + len(after),
            "truncated": total > 50,
            "es_query": body,
            "took_ms": int((time.time() - t0) * 1000)
        })
    except Exception as e:
        return _error(str(e))

# -----------------------------------------------------------------------------
# 5. validate_detection_rule
# -----------------------------------------------------------------------------

def validate_detection_rule(query, start: str = "now-48h", end: str = "now") -> dict:
    t0 = time.time()
    try:
        # 1. Parse incoming query
        if isinstance(query, str):
            query = json.loads(query)
            
        input_query = query.get("query", query)
        
        # 2. Extract existing filter clauses safely
        if "bool" in input_query and "filter" in input_query["bool"]:
            existing_filters = input_query["bool"]["filter"]
            if not isinstance(existing_filters, list):
                existing_filters = [existing_filters]
        else:
            existing_filters = [input_query]
            
        # 3. Add time range
        all_filters = existing_filters + [
            {"range": {"@timestamp": {"gte": _normalize_time(start), "lte": _normalize_time(end)}}}
        ]
        
        # 4. Build body with labels.is_threat
        body = {
            "query": {"bool": {"filter": all_filters}},
            "_source": ["labels.is_threat", "@timestamp", "source.ip", "message"],
            "size": 500
        }
        
        # 5. Search including labels
        res = es_client.search(body, include_labels=True)
        hits = res["hits"]["hits"]
        total = res["hits"]["total"]["value"]
        
        # 6. Calculate True Positives / False Positives
        tps = 0
        fps = 0
        sample_fps = []
        
        for h in hits:
            source = h.get("_source", {})
            labels = source.get("labels", {})
            is_threat = labels.get("is_threat", False)
            
            if is_threat:
                tps += 1
            else:
                fps += 1
                if len(sample_fps) < 3:
                    # Strip labels from the sample before storing
                    safe_sample = dict(source)
                    safe_sample.pop("labels", None)
                    sample_fps.append(safe_sample)
                    
        fp_rate = (fps / total) if total > 0 else 0.0
        
        data = {
            "matches": total,
            "true_positives": tps,
            "false_positives": fps,
            "fp_rate": fp_rate,
            "sample_fps": sample_fps
        }
        
        return _envelope(data, {
            "hits_total": total,
            "returned": len(hits),
            "truncated": total > 500,
            "es_query": body,
            "took_ms": int((time.time() - t0) * 1000)
        })
    except Exception as e:
        return _error(str(e))
