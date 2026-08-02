import { useState } from "react";
import * as api from "../lib/api";
import { normalizeSeverity, verdictFindings } from "../lib/runState";
import Markdown from "./Markdown";

/* The verdict card, plus the two actions that hang off it.
 *
 * Timeline bypasses the model entirely (straight to MCP, ~200ms) because it
 * backs a button a judge clicks - it must be fast and unbreakable. */

function Timeline({ data, onClose }) {
  const { before = [], after = [], summary = {}, anchor, host } = data;
  const time = (t) => (t || "").slice(11, 16);

  return (
    <div className="tl">
      <header className="tl-head">
        <div>
          <span className="eyebrow">Incident window</span>
          <p className="mono tl-anchor">
            {host} · {anchor}
          </p>
        </div>
        <button className="btn-close" onClick={onClose} aria-label="Close timeline">
          Close
        </button>
      </header>

      <div className="tl-cols">
        <section className="tl-col">
          <h4 className="tl-col-head">
            Before <span className="mono">15m</span>
          </h4>
          {before.map((e, i) => (
            <p key={i} className="tl-row">
              <span className="mono tl-time">{time(e["@timestamp"])}</span>
              <span className="tl-text">{e["event.action"] || e.message}</span>
            </p>
          ))}
          <p className="tl-note">
            {before.length ? "Routine activity" : "Nothing logged"}
          </p>
        </section>

        <section className="tl-col loud">
          <h4 className="tl-col-head">
            After <span className="mono">15m</span>
          </h4>
          {after.map((e, i) => (
            <p key={i} className="tl-row">
              <span className="mono tl-time">{time(e["@timestamp"])}</span>
              <span className="tl-text">
                {e["process.name"]
                  ? `${e["event.action"]} — ${e["process.name"]}`
                  : e["event.action"] || e.message}
              </span>
            </p>
          ))}
          {summary.new_categories_after?.length > 0 && (
            <p className="tl-note loud">
              {summary.new_categories_after.length} new event categor
              {summary.new_categories_after.length === 1 ? "y" : "ies"}:{" "}
              <span className="mono">
                {summary.new_categories_after.join(", ")}
              </span>
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

function Sigma({ data, onClose }) {
  const v = data.validation || {};
  return (
    <div className="sig">
      <header className="tl-head">
        <div>
          <span className="eyebrow">Detection rule</span>
          <p className="sig-headline">{data.headline}</p>
        </div>
        <button className="btn-close" onClick={onClose} aria-label="Close rule">
          Close
        </button>
      </header>

      <div className="sig-stats">
        <div className="stat">
          <span className="stat-n mono">{v.matches ?? "—"}</span>
          <span className="stat-l">matches</span>
        </div>
        <div className="stat">
          <span className="stat-n mono ok">{v.true_positives ?? "—"}</span>
          <span className="stat-l">true positives</span>
        </div>
        <div className="stat">
          <span className="stat-n mono warn">{v.false_positives ?? "—"}</span>
          <span className="stat-l">false positives</span>
        </div>
        <div className="stat">
          <span className="stat-n mono">
            {v.fp_rate != null ? `${(v.fp_rate * 100).toFixed(1)}%` : "—"}
          </span>
          <span className="stat-l">FP rate</span>
        </div>
      </div>

      <pre className="sig-yaml mono">{data.yaml}</pre>
    </div>
  );
}

export default function Verdict({ verdict, streamed }) {
  const [panel, setPanel] = useState(null); // null | 'timeline' | 'sigma'
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);

  async function open(kind) {
    if (panel === kind) return setPanel(null);
    setBusy(kind);
    setErr(null);
    try {
      if (kind === "timeline") {
        const res = await api.timeline();
        // MCP never raises; a failure arrives as an empty envelope with
        // meta.error, so check that rather than trusting the 200.
        if (res.meta?.error) throw new Error(res.meta.error);
        setData(res.data);
      } else {
        setData(await api.forgeSigma({ findings: verdictFindings(verdict) }));
      }
      setPanel(kind);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  // Before the verdict lands, show the streaming narration so the pane is
  // never empty while the model is still writing.
  if (!verdict) {
    if (!streamed) return null;
    return (
      <div className="verdict streaming">
        <span className="eyebrow">Assessment</span>
        <Markdown text={streamed} className="verdict-body" />
        <span className="caret" aria-hidden="true" />
      </div>
    );
  }

  const sev = normalizeSeverity(verdict.severity);
  const findings = verdictFindings(verdict);
  // Timeline needs an anchor. The backend falls back to session findings, so
  // only disable when we know there is nothing to anchor on.
  const canTimeline = !findings || Boolean(findings.anchor_timestamp);

  // Prefer the streamed narration. `summary` is a truncated prefix of the same
  // text (the agent cuts it at 200 chars and appends an ellipsis), so using it
  // when the full text is in hand would throw away most of the assessment.
  const body = streamed?.trim() || verdict.summary || "";

  return (
    <div className="verdict">
      <header className="verdict-head">
        <span className={`sev sev-${sev}`}>{verdict.severity || sev}</span>
        <span className="eyebrow">Assessment</span>
      </header>

      <Markdown text={body} className="verdict-body" />

      {verdict.iocs?.length > 0 && (
        <div className="iocs">
          <span className="eyebrow">Indicators</span>
          <ul>
            {verdict.iocs.map((i) => (
              <li key={i} className="mono">
                {i}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="verdict-actions">
        <button
          className="btn-ghost sm"
          onClick={() => open("timeline")}
          disabled={Boolean(busy) || !canTimeline}
          aria-pressed={panel === "timeline"}
          title={canTimeline ? undefined : "No incident timestamp in this run"}
        >
          {busy === "timeline" ? "Loading…" : "Inspect timeline"}
        </button>
        <button
          className="btn-ghost sm"
          onClick={() => open("sigma")}
          disabled={Boolean(busy)}
          aria-pressed={panel === "sigma"}
        >
          {busy === "sigma" ? "Forging…" : "Forge detection rule"}
        </button>
      </div>

      {err && <p className="trace-error">{err}</p>}
      {panel === "timeline" && data && (
        <Timeline data={data} onClose={() => setPanel(null)} />
      )}
      {panel === "sigma" && data && (
        <Sigma data={data} onClose={() => setPanel(null)} />
      )}
    </div>
  );
}
