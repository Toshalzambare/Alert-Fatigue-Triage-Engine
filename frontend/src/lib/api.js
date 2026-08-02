
/* Backend client.
 *
 * The contract with Flask (plan 05): POST /api/ask returns a job_id, then
 * GET /api/stream/<job_id> streams contract §1 events over SSE.
 *
 * We use fetch + ReadableStream rather than EventSource because EventSource
 * cannot POST and cannot set headers - we would need a second request just to
 * open the stream. This also gives us a clean abort path.
 */

/* Empty by default: Vite proxies /api to Flask, so the browser sees one origin
 * and CORS never enters the picture. Set VITE_API_BASE to point at a backend on
 * another host. */
const BASE = import.meta.env.VITE_API_BASE || "";

let sessionId = null;

export function getSessionId() {
  return sessionId;
}

async function postJSON(path, body) {
  const res = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

export async function health() {
  const res = await fetch(BASE + "/api/health");
  if (!res.ok) throw new Error("backend unreachable");
  return res.json();
}

/* Drain an SSE stream, calling onEvent for each parsed event.
 *
 * Buffers partial frames: a chunk boundary can land mid-JSON, and parsing
 * eagerly would throw on perfectly valid data. */
async function consumeStream(jobId, onEvent, signal) {
  const res = await fetch(`${BASE}/api/stream/${jobId}`, {
    headers: { Accept: "text/event-stream" },
    signal,
  });
  if (!res.ok) throw new Error(`stream failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data:")) continue; // ": keepalive" comments
      try {
        const ev = JSON.parse(line.slice(5).trim());
        onEvent(ev);
        if (ev.type === "eof") return;
      } catch {
        /* a malformed frame must never kill the run */
      }
    }
  }
}

export async function ask(question, onEvent, signal) {
  const { job_id, session_id } = await postJSON("/api/ask", {
    question,
    session_id: sessionId,
  });
  sessionId = session_id;
  await consumeStream(job_id, onEvent, signal);
  return job_id;
}

export async function uploadImage(file, question, onEvent, signal) {
  const form = new FormData();
  form.append("image", file);
  form.append("question", question || "Did anyone click this?");
  if (sessionId) form.append("session_id", sessionId);

  const res = await fetch(BASE + "/api/upload", { method: "POST", body: form });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "upload failed");

  sessionId = data.session_id;
  await consumeStream(data.job_id, onEvent, signal);
  return data;
}

/* Bypasses the agent entirely - straight to MCP, ~200ms. Backs a button a
 * judge clicks, so it must be fast and unbreakable. */
export function timeline({ anchor, host } = {}) {
  return postJSON("/api/timeline", { session_id: sessionId, anchor, host });
}

export function forgeSigma() {
  return postJSON("/api/sigma", { session_id: sessionId, stream: false });
}
