"""In-memory job + session state.

Plan 05 Phase 3: "A plain dict is correct for a 4-hour demo; anything more is
time you don't have." No database, deliberately.

Two things live here:
  Job     - one agent run: a queue of SSE events, a status, a final result.
  Session - what the analyst has found so far, so /api/timeline and /api/sigma
            know "what did we just find" without an NL round-trip.
"""
import threading
import time
import uuid
from dataclasses import dataclass, field
from queue import Queue

# Pushed into a job queue to mean "no more events". Identity-compared, so it
# must be a unique object rather than None (a legitimate event could be falsy).
SENTINEL = object()


@dataclass
class Job:
    """One agent run. The queue is drained by exactly one SSE consumer."""

    id: str
    session_id: str
    question: str = ""
    status: str = "running"  # running | done | error
    queue: Queue = field(default_factory=Queue)
    events: list = field(default_factory=list)  # replayed to a late subscriber
    result: dict | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)

    def emit(self, event: dict) -> None:
        """The single integration surface between the agent and Flask.

        Agreed with Teammate D (plan 05 Phase 2): one function, one dict arg,
        shapes per contract §1. The agent never imports Flask.
        """
        event.setdefault("ts", time.time())
        # seq is assigned by this job, never inherited. Replayed events arrive
        # carrying stale seq values from the run that recorded them; letting
        # those through would break the SSE late-subscriber dedup and the
        # ?since=N polling cursor.
        event["seq"] = len(self.events)
        self.events.append(event)
        self.queue.put(event)

    def close(self) -> None:
        self.queue.put(SENTINEL)


@dataclass
class Session:
    """Carried across questions so Timeline / Sigma have context."""

    id: str
    findings: dict = field(default_factory=dict)
    tool_calls: list = field(default_factory=list)
    last_verdict: dict | None = None
    created_at: float = field(default_factory=time.time)


class Store:
    """Thread-safe registry. Flask worker threads write, SSE threads read."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    # --- jobs ---
    def create_job(self, session_id: str, question: str = "") -> Job:
        job = Job(id=uuid.uuid4().hex, session_id=session_id, question=question)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def job_count(self) -> int:
        with self._lock:
            return len(self._jobs)

    # --- sessions ---
    def get_session(self, session_id: str | None) -> Session:
        """Fetch or create. A missing/unknown id silently mints a new session -
        a demo should never 404 because a browser tab was refreshed."""
        sid = session_id or uuid.uuid4().hex
        with self._lock:
            sess = self._sessions.get(sid)
            if sess is None:
                sess = Session(id=sid)
                self._sessions[sid] = sess
            return sess

    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    # --- housekeeping ---
    def sweep(self, max_age_s: int = 3600) -> int:
        """Drop finished jobs older than max_age_s so a long demo doesn't grow
        unbounded. Running jobs are never swept."""
        cutoff = time.time() - max_age_s
        with self._lock:
            stale = [
                jid
                for jid, j in self._jobs.items()
                if j.status != "running" and j.created_at < cutoff
            ]
            for jid in stale:
                del self._jobs[jid]
        return len(stale)


STORE = Store()
