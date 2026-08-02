import { useState } from "react";
import { efficiencyLine, triageEntities } from "../lib/runState";

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

function Efficiency({ meta }) {
  const e = efficiencyLine(meta);
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
          <span className="hop-n mono">Hop {hop.label}</span>
          <span className="hop-tool mono">{hop.tool}</span>
          {!hop.result && !hop.healing.length && (
            <span className="hop-wait" aria-label="Running" />
          )}
        </header>

        {hop.args && Object.keys(hop.args).length > 0 && (
          <p className="hop-args mono">
            {Object.entries(hop.args)
              .filter(([, v]) => v !== null && v !== undefined && v !== "")
              .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`)
              .join("  ")}
          </p>
        )}

        {settled?.meta?.error && (
          <p className="hop-empty">{settled.meta.error}</p>
        )}
        {empty && !settled?.meta?.error && <p className="hop-empty">No results</p>}
        <Healing items={hop.healing} />

        {settled?.meta && (
          <>
            <Efficiency meta={settled.meta} />
            <EsQuery query={settled.meta.es_query} />
          </>
        )}
      </article>

      {/* The connector reason is the proof of autonomy: the agent chose the
          next step and said why. Rendered whenever a reason exists, including
          on the last card - a stated pivot that did not complete is still
          information, and hiding it would make a failed run look like a
          deliberate stop. */}
      {hop.reason && (
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
            <p className="mono">intent={run.triage.intent}</p>
            {triageEntities(run.triage.entities).map((e, i) => (
              <p key={i} className="triage-entity">
                {e}
              </p>
            ))}
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
            <Hop key={`${h.tool}-${h.n}-${i}`} hop={h} />
          ))}
        </ol>

        {run.error && (
          <p className="trace-error">
            <span className="trace-error-bar" aria-hidden="true" />
            {run.error}
          </p>
        )}
      </div>
    </section>
  );
}
