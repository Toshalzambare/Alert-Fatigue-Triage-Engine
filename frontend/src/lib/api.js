/* Backend client.
 *
 * Contract: POST /api/ask returns a job_id, then GET /api/stream/<job_id>
 * streams events over SSE. Every event carries a `seq`, which is what lets us
 * resume a dropped stream without replaying what the UI already rendered.
 *
 * fetch + ReadableStream rather than EventSource: EventSource cannot POST and
 * cannot set headers, so it would need a second request just to open the
 * stream, and it gives no clean abort path.
 */

/* Empty by default: Vite proxies /api to Flask, so the browser sees one origin
 * and CORS never enters the picture. Set VITE_API_BASE to reach a backend on
 * another host. */
const BASE = import.meta.env.VITE_API_BASE || "";

let sessionId = null;

export function getSessionId() {
  return sessionId;
}

function rememberSession(id) {
  if (id) sessionId = id;
  return id;
}

async function request(path, options = {}) {
  const res = await fetch(BASE + path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `${res.status} ${res.statusText}`);
    err.status = res.status;
    err.detail = data.detail;
    throw err;
  }
  return data;
}

function postJSON(path, body) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function health() {
  return request("/api/health");
}

export function jobStatus(jobId) {
  return request(`/api/job/${jobId}`);
}

/* ------------------------------------------------------------- streaming --- */

/* Read one SSE response, dispatching events. Returns the highest seq seen so a
 * reconnect can resume from exactly there. Resolves `done` when the stream
 * ended deliberately (eof), false when the connection simply stopped. */
async function readStream(jobId, from, onEvent, signal) {
  const res = await fetch(`${BASE}/api/stream/${jobId}`, {
    headers: { Accept: "text/event-stream" },
    signal,
  });
  if (!res.ok) throw new Error(`stream failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let seq = from;
  let done = false;

  try {
    while (true) {
      const { done: closed, value } = await reader.read();
      if (closed) break;
      buffer += decoder.decode(value, { stream: true });

      // A chunk boundary can land mid-JSON, so only parse complete frames.
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const line = frame.trim();
        if (!line.startsWith("data:")) continue; // ": keepalive" comments
        let ev;
        try {
          ev = JSON.parse(line.slice(5).trim());
        } catch {
          continue; // a malformed frame must never kill the run
        }
        if (typeof ev.seq === "number") {
          if (ev.seq < seq) continue; // already delivered before a reconnect
          seq = ev.seq + 1;
        }
        if (ev.type === "eof") {
          done = true;
          return { seq, done };
        }
        onEvent(ev);
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
  return { seq, done };
}

/* Drain everything still buffered for a job, by sequence cursor. Used to
 * recover after a dropped connection - the backend keeps a replayable backlog
 * in Redis, so nothing is lost. */
async function drainBacklog(jobId, from, onEvent) {
  const { events, next_since, status } = await request(
    `/api/events/${jobId}?since=${from}`
  );
  for (const ev of events) {
    if (ev.type === "eof") return { seq: next_since, done: true, status };
    onEvent(ev);
  }
  return { seq: next_since, done: status !== "running" && status !== "queued", status };
}

/* Follow a job to completion, reconnecting if the stream drops mid-run.
 *
 * Long investigations outlive flaky connections; without this a transient
 * network blip would silently freeze the trace pane with no error shown. */
async function follow(jobId, onEvent, signal, { retries = 3 } = {}) {
  let seq = 0;
  let attempt = 0;

  while (true) {
    try {
      const r = await readStream(jobId, seq, onEvent, signal);
      seq = r.seq;
      if (r.done) return;
      // Stream ended without eof: the run may still be going.
      const b = await drainBacklog(jobId, seq, onEvent);
      seq = b.seq;
      if (b.done) return;
    } catch (e) {
      if (e.name === "AbortError" || signal?.aborted) return;
      if (++attempt > retries) throw e;
      await new Promise((r) => setTimeout(r, 400 * attempt));
      // Catch up on anything emitted while we were disconnected.
      try {
        const b = await drainBacklog(jobId, seq, onEvent);
        seq = b.seq;
        if (b.done) return;
      } catch {
        /* fall through and retry the stream */
      }
    }
  }
}

/* ---------------------------------------------------------------- actions --- */

export async function ask(question, onEvent, signal) {
  const { job_id, session_id } = await postJSON("/api/ask", {
    question,
    session_id: sessionId,
  });
  rememberSession(session_id);
  await follow(job_id, onEvent, signal);
  return job_id;
}

export async function uploadImage(file, question, onEvent, signal) {
  const form = new FormData();
  form.append("image", file);
  if (question) form.append("question", question);
  if (sessionId) form.append("session_id", sessionId);

  const data = await request("/api/upload", { method: "POST", body: form });
  rememberSession(data.session_id);
  await follow(data.job_id, onEvent, signal);
  return data;
}

/* Bypasses the agent entirely - straight to MCP, ~200ms. Backs a button a
 * judge clicks, so it must be fast and unbreakable. */
export function timeline({ anchor, host } = {}) {
  return postJSON("/api/timeline", { session_id: sessionId, anchor, host });
}

export function forgeSigma({ findings } = {}) {
  return postJSON("/api/sigma", {
    session_id: sessionId,
    findings,
    stream: false,
  });
}

export function session() {
  if (!sessionId) return Promise.resolve(null);
  return request(`/api/session/${sessionId}`);
}
