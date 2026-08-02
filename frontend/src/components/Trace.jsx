import { useState } from "react";
import { efficiencyLine } from "../lib/runState";

/* The reasoning trace. This pane is the product.
 *
 * Hop cards appear in sequence as events arrive - never batch-rendered at the
 * end, because the sequence is what proves the agent is investigating rather
 * than answering. */

function EsQuery({ query }) {
  const [open, setOpen] = useState(false);
  if (!query || !Object.keys(query).length) return null;
  return (
    <div className="esq">
      <button
        className="esq-toggle"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <span className="esq-caret" data-open={open} aria-hidden="true" />
        {open ? "Hide" : "View"} Elastic query
      </button>
      {open && (
        <pre className="esq-body mono">{JSON.stringify(query, null, 2)}</pre>
      )}
    </div>
  );
}

function Efficiency({ meta, tool }) {
  const e = efficiencyLine(meta, tool);
  return (
    <p className="eff mono">
      <span className="eff-primary">{e.primary}</span>
      {e.secondary && <span className="eff-sep">·</span>}
      {e.secondary && <span>{e.secondary}</span>}
      {e.took != null && <span className="eff-sep">·</span>}
      {e.took != null && <span>{e.took}ms</span>}
    </p>
  );
}

/* Amber, never red. Red reads as broken; amber reads as recovering, and that
 * distinction is the entire self-healing feature. */
function Healing({ items }) {
  if (!items.length) return null;
  return (
    <div className="heal">
      {items.map((h, i) =>
        h.attempt ? (
          <p key={i} className="heal-line">
            <span className="heal-icon" aria-hidden="true" />
            Retry {h.attempt.attempt} — {h.attempt.fix.replace(/_/g, " ")}:{" "}
            <span className="mono heal-from">{h.attempt.from}</span>
            <span className="heal-arrow" aria-hidden="true" />
            <span className="mono heal-to">{h.attempt.to}</span>
          </p>
        ) : (
          <p key={i} className="heal-ok">
            Recovered — {h.result.meta?.hits_total ?? 0} results
          </p>
        )
      )}
    </div>
  );
}

function Hop({ hop, isLast }) {
  const empty = hop.result?.meta?.hits_total === 0 && !hop.healing.length;
  const healed = hop.healing.length > 0;
  const settled = hop.healing.find((h) => h.result)?.result ?? hop.result;

  return (
    <li className="hop">
      <article className={`hop-card ${healed ? "healed" : ""}`}>
        <header className="hop-head">
          <span className="hop-n mono">Hop {hop.n}</span>
          <span className="hop-tool mono">{hop.tool}</span>
          {!hop.result && <span className="hop-wait" aria-label="Running" />}
        </header>

        {hop.args && (
          <p className="hop-args mono">
            {Object.entries(hop.args)
              .filter(([, v]) => v !== null && v !== undefined && v !== "")
              .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`)
              .join("  ")}
          </p>
        )}

        {empty && <p className="hop-empty">No results</p>}
        <Healing items={hop.healing} />

        {settled?.meta && (
          <>
            <Efficiency meta={settled.meta} tool={hop.tool} />
            <EsQuery query={settled.meta.es_query} />
          </>
        )}
      </article>

      {/* The connector reason is the proof of autonomy: the agent chose the
          next step and said why. */}
      {hop.reason && !isLast && (
        <p className="hop-reason">
          <span className="hop-reason-rule" aria-hidden="true" />
          {hop.reason}
        </p>
      )}
    </li>
  );
}

export default function Trace({ run, scrollRef }) {
  const idle = run.status === "idle";

  return (
    <section className="trace" aria-label="Agent reasoning trace">
      <header className="trace-head">
        <span className="eyebrow">Reasoning trace</span>
        {run.status === "running" && (
          <span className="trace-live">
            <span className="live" aria-hidden="true" />
            <span className="mono">running</span>
          </span>
        )}
      </header>

      <div className="trace-body" ref={scrollRef}>
        {idle && (
          <p className="trace-idle">
            Each tool call, hop, and retry appears here as the agent works.
          </p>
        )}

        {run.triage && (
          <div className="triage">
            <span className="eyebrow">Triage</span>
            <p className="mono">
              intent={run.triage.intent}
              {run.triage.entities &&
                Object.entries(run.triage.entities).map(([k, v]) => (
                  <span key={k}>{`  ${k}=${v}`}</span>
                ))}
            </p>
          </div>
        )}

        {run.vision && (
          <div className="vision">
            <span className="eyebrow">Vision analysis</span>
            <dl className="vision-grid">
              <dt>Brand impersonated</dt>
              <dd>{run.vision.brand_impersonated}</dd>
              <dt>Extracted domain</dt>
              <dd className="mono vision-domain">
                {run.vision.extracted_domain}
                {run.vision.typosquat && (
                  <span className="tag-warn">typosquat</span>
                )}
              </dd>
              {run.vision.red_flags?.length > 0 && (
                <>
                  <dt>Red flags</dt>
                  <dd>{run.vision.red_flags.join(", ")}</dd>
                </>
              )}
            </dl>
            <p className="vision-next">
              Searching logs for this domain
            </p>
          </div>
        )}

        {run.injection && (
          <div className="injection" role="status">
            <span className="injection-bar" aria-hidden="true" />
            Prompt injection found in log data — neutralized.
            <span className="mono injection-pattern">
              “{run.injection.pattern}”
            </span>
          </div>
        )}

        <ol className="hops">
          {run.hops.map((h, i) => (
            <Hop key={`${h.tool}-${h.n}-${i}`} hop={h} isLast={i === run.hops.length - 1} />
          ))}
        </ol>

        {run.error && <p className="trace-error">{run.error}</p>}
      </div>
    </section>
  );
}
