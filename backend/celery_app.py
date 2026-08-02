"""Celery application and the event bus that carries agent events back to Flask.

Why this exists
---------------
The agent's LLM calls take 5-30s. Running them in Flask worker threads caps
concurrency at the size of the thread pool and ties every run to the lifetime of
one web process - a restart kills in-flight investigations.

Celery moves the agent into separate worker processes. That buys horizontal
scale (add workers, not web servers) and isolation (a worker OOM does not take
down the API).

The consequence: `emit()` can no longer push into an in-process queue, because
the producer and the consumer are now in different processes. Events travel over
Redis pub/sub instead, and the SSE route subscribes to a per-job channel.

    Celery worker                  Redis                    Flask
    agent emit(ev) ──publish──►  job:<id>  ──subscribe──►  SSE generator

A Redis list mirrors every event so a late subscriber (or the polling fallback)
can replay what it missed - pub/sub alone drops messages sent before subscribe.
"""
import json
import logging

from celery import Celery
from redis import Redis

import config

log = logging.getLogger("backend.celery")

celery_app = Celery(
    "sentinel",
    broker=config.REDIS_URL,
    backend=config.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # An investigation that has not finished in 5 minutes is wedged. Kill it
    # rather than letting it hold a worker slot through a demo.
    task_time_limit=config.TASK_HARD_LIMIT_S,
    task_soft_time_limit=config.TASK_SOFT_LIMIT_S,
    # LLM work is long and stateful; prefetching would starve idle workers.
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
)

_redis: Redis | None = None


def redis() -> Redis:
    """Lazy shared connection. decode_responses keeps callers on str, not bytes."""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(config.REDIS_URL, decode_responses=True)
    return _redis


def channel(job_id: str) -> str:
    return f"job:{job_id}:events"


def backlog_key(job_id: str) -> str:
    return f"job:{job_id}:backlog"


def state_key(job_id: str) -> str:
    return f"job:{job_id}:state"


# --------------------------------------------------------------- publish ---
def publish(job_id: str, event: dict) -> int:
    """Append to the backlog, then fan out to any live subscriber.

    Order matters: writing the backlog first means a subscriber that connects
    between the two calls sees the event in its replay rather than missing it.
    """
    r = redis()
    seq = r.rpush(backlog_key(job_id), json.dumps(event)) - 1
    event["seq"] = seq
    # Overwrite the stored copy so the backlog and the live stream agree on seq.
    r.lset(backlog_key(job_id), seq, json.dumps(event))
    r.expire(backlog_key(job_id), config.JOB_TTL_S)
    r.publish(channel(job_id), json.dumps(event))
    return seq


def read_backlog(job_id: str, since: int = 0) -> list[dict]:
    raw = redis().lrange(backlog_key(job_id), since, -1)
    return [json.loads(x) for x in raw]


def set_state(job_id: str, **fields) -> None:
    r = redis()
    key = state_key(job_id)
    r.hset(key, mapping={k: json.dumps(v) for k, v in fields.items()})
    r.expire(key, config.JOB_TTL_S)


def get_state(job_id: str) -> dict:
    raw = redis().hgetall(state_key(job_id))
    out = {}
    for k, v in raw.items():
        try:
            out[k] = json.loads(v)
        except (json.JSONDecodeError, TypeError):
            out[k] = v
    return out


# ---------------------------------------------------------------- health ---
def broker_available() -> bool:
    try:
        return redis().ping()
    except Exception:  # noqa: BLE001
        return False


def workers_online() -> int:
    """Count responding workers. Used by /api/health so a missing worker is
    visible immediately rather than as jobs that silently never start."""
    try:
        replies = celery_app.control.ping(timeout=0.4)
        return len(replies or [])
    except Exception:  # noqa: BLE001
        return 0
