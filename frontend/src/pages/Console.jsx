import { useEffect, useRef, useState } from "react";
import Trace from "../components/Trace";
import VerdictCard from "../components/Verdict";
import * as api from "../lib/api";
import { emptyRun, reduceEvent } from "../lib/runState";
import "./console.css";

const SUGGESTED = [
  "What IPs seem malicious today and why?",
  "Did anyone log in from two countries at once?",
  "Show me what happened around the vpn-gw-01 incident.",
];

export default function Console({ onExit }) {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState(null); // the question this run is answering
  const [run, setRun] = useState(emptyRun);
  const [status, setStatus] = useState(null);
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);

  const traceRef = useRef(null);
  const abortRef = useRef(null);
  const inputRef = useRef(null);

  // Object URLs leak unless revoked, and calling createObjectURL inline would
  // mint a fresh one on every render - once per streamed token.
  const [preview, setPreview] = useState(null);
  useEffect(() => {
    if (!file) return setPreview(null);
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  // Poll health so a worker or MCP server dying mid-session is visible in the
  // header rather than showing up as a run that never produces events.
  useEffect(() => {
    let alive = true;
    const check = () =>
      api
        .health()
        .then((h) => alive && setStatus(h))
        .catch(() => alive && setStatus({ unreachable: true }));
    check();
    const id = setInterval(check, 15000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // Auto-scroll the trace as hops arrive, so the newest card stays visible
  // without the layout jumping mid-demo.
  useEffect(() => {
    const el = traceRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [run.hops, run.tokens, run.verdict]);

  async function submit(text, image) {
    const q = (text ?? question).trim();
    if (!q && !image) return;

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setRun({ ...emptyRun, status: "running" });
    setAsked(q || "Did anyone click this?");
    setFile(image ?? null); // a text-only run must not show a stale thumbnail
    setQuestion("");

    const onEvent = (ev) => setRun((r) => reduceEvent(r, ev));

    try {
      if (image) {
        await api.uploadImage(image, q, onEvent, ctrl.signal);
      } else {
        await api.ask(q, onEvent, ctrl.signal);
      }
      setRun((r) => (r.status === "running" ? { ...r, status: "done" } : r));
    } catch (e) {
      if (e.name === "AbortError" || ctrl.signal.aborted) return;
      const detail = e.detail ? ` — ${e.detail}` : "";
      setRun((r) => ({ ...r, status: "error", error: e.message + detail }));
    }
  }

  function stop() {
    abortRef.current?.abort();
    setRun((r) => ({ ...r, status: "done" }));
  }

  function onDrop(e) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f?.type.startsWith("image/")) {
      setFile(f);
      submit(question || "Did anyone click this?", f);
    }
  }

  const started = run.status !== "idle";
  const running = run.status === "running";

  return (
    <div className="console">
      <header className="c-nav">
        <button className="c-back" onClick={onExit}>
          <span className="c-back-arrow" aria-hidden="true" />
          Sentinel
        </button>

        <div className="c-status">
          {status?.unreachable ? (
            <span className="c-badge err">Backend unreachable</span>
          ) : status ? (
            <>
              <span className="mono c-mode">
                {status.subsystems?.llm?.provider ?? "unknown"}
              </span>
              {status.degraded?.length > 0 ? (
                <span className="c-badge err" title="These subsystems are down">
                  {status.degraded.join(" · ")} down
                </span>
              ) : (
                <span className="c-badge ok">all systems ready</span>
              )}
            </>
          ) : null}
        </div>
      </header>

      <main
        className={`c-grid ${dragging ? "dragging" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        {/* --------------------------------------------------- left pane --- */}
        <section className="c-chat" aria-label="Analyst console">
          {!started && (
            <div className="c-empty">
              <h1>What do you want to know?</h1>
              <p className="c-empty-sub">
                Ask in plain English, or drop a screenshot to trace a phishing
                campaign through your logs.
              </p>
              <ul className="c-suggest">
                {SUGGESTED.map((s) => (
                  <li key={s}>
                    <button onClick={() => submit(s)}>{s}</button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {started && (
            <div className="c-thread">
              <p className="c-asked">{asked}</p>

              {file && preview && (
                <figure className="c-upload">
                  <img src={preview} alt="Uploaded screenshot" />
                  <figcaption className="mono">{file.name}</figcaption>
                </figure>
              )}

              <VerdictCard verdict={run.verdict} streamed={run.tokens} />

              {running && !run.tokens && !run.verdict && (
                <p className="c-working">
                  <span className="live" aria-hidden="true" />
                  Investigating
                  <button className="c-stop" onClick={stop}>
                    Stop
                  </button>
                </p>
              )}

              {run.status === "error" && !run.verdict && (
                <div className="c-failed">
                  <span className="eyebrow">Run failed</span>
                  <p>{run.error}</p>
                </div>
              )}
            </div>
          )}

          <form
            className="c-form"
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <input
              ref={inputRef}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about your logs"
              aria-label="Your question"
              disabled={running}
            />
            <label className="c-attach" title="Attach a screenshot">
              <input
                type="file"
                accept="image/*"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) {
                    setFile(f);
                    submit(question || "Did anyone click this?", f);
                  }
                }}
              />
              <span className="c-clip" aria-hidden="true" />
              <span className="sr">Attach image</span>
            </label>
            <button
              className="btn-primary sm"
              type="submit"
              disabled={running || !question.trim()}
            >
              Ask
            </button>
          </form>
        </section>

        {/* -------------------------------------------------- right pane --- */}
        <Trace run={run} scrollRef={traceRef} />
      </main>

      {dragging && (
        <div className="c-dropzone">
          <p>Drop the screenshot to search your logs for it</p>
        </div>
      )}
    </div>
  );
}
