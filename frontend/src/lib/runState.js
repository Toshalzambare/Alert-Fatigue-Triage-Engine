/* Folds the flat SSE event stream into the shape the trace pane renders.
 *
 * The backend emits events in sequence; the UI needs them grouped into hops,
 * with healing attempts nested under the call they recovered. Doing that here
 * keeps the components dumb and the grouping in one testable place.
 *
 * Everything in this file is defensive about shape. The agent is a 12B model
 * driving a graph - fields arrive missing, capitalised differently, or as a
 * string where an object was expected. A render must never throw on that.
 */

export const emptyRun = {
  status: "idle", // idle | running | done | error
  triage: null,
  hops: [], // { n, tool, args, result, healing[], reason }
  vision: null,
  injection: null,
  tokens: "",
  verdict: null,
  error: null,
};

/* Field projection is the rubric claim: "only pulls the data it needs".
 * These derive the one line that proves it, per tool shape. */
export function efficiencyLine(meta = {}) {
  const hits = meta.hits_total ?? 0;
  const returned = meta.returned ?? 0;
  const fields = meta.fields_returned?.length ?? 0;

  // An aggregation collapses documents into a profile: no raw docs come back.
  const isAggregation = meta.raw_documents === 0 || (hits > 0 && returned === 0);

  return {
    primary: isAggregation
      ? `${hits.toLocaleString()} events → 1 profile`
      : `${hits.toLocaleString()} hits → ${returned} returned`,
    secondary: isAggregation
      ? "0 raw documents · aggregation only"
      : fields
        ? `${fields} fields`
        : null,
    took: meta.took_ms ?? null,
  };
}

/* The agent labels severity inconsistently ("High" vs "high"). Normalise for
 * the CSS class, and fall back rather than rendering an unstyled badge. */
export function normalizeSeverity(value) {
  const s = String(value || "").toLowerCase();
  if (s.startsWith("crit") || s.startsWith("high")) return "high";
  if (s.startsWith("med")) return "medium";
  if (s.startsWith("low") || s.startsWith("info")) return "low";
  return "medium";
}

/* triage.entities arrives as an array of strings from the live agent, but the
 * event contract describes an object. Render either without complaint. */
export function triageEntities(entities) {
  if (!entities) return [];
  if (Array.isArray(entities)) return entities.filter(Boolean).map(String);
  if (typeof entities === "object") {
    return Object.entries(entities)
      .filter(([, v]) => v !== null && v !== undefined && v !== "")
      .map(([k, v]) => `${k}=${v}`);
  }
  return [String(entities)];
}

/* A verdict's findings may be a structured object or the raw narration. Only
 * an object can drive the timeline/sigma buttons. */
export function verdictFindings(verdict) {
  const f = verdict?.findings;
  return f && typeof f === "object" && !Array.isArray(f) ? f : null;
}

function matchHop(hops, ev) {
  // Prefer an exact hop number; fall back to the most recent call of that tool.
  for (let i = hops.length - 1; i >= 0; i--) {
    if (ev.hop !== undefined && hops[i].n === ev.hop && hops[i].tool === ev.tool) return i;
  }
  for (let i = hops.length - 1; i >= 0; i--) {
    if (hops[i].tool === ev.tool) return i;
  }
  return hops.length - 1;
}

export function reduceEvent(run, ev) {
  const next = { ...run };
  if (next.status === "idle") next.status = "running";

  switch (ev.type) {
    case "triage":
      next.triage = ev;
      break;

    case "vision":
      next.vision = ev;
      break;

    case "tool_call":
      next.hops = [
        ...next.hops,
        {
          // The agent counts hops from 0; humans count from 1.
          n: ev.hop ?? next.hops.length,
          label: (ev.hop ?? next.hops.length) + 1,
          tool: ev.tool,
          args: ev.args,
          result: null,
          healing: [],
          reason: null,
        },
      ];
      break;

    case "tool_result": {
      if (!next.hops.length) break;
      const hops = [...next.hops];
      const i = matchHop(hops, ev);
      if (i < 0) break;
      // A healing retry arrives as a second result for the SAME hop, so it
      // must attach as a recovery rather than overwrite the original.
      hops[i] = ev.healing
        ? { ...hops[i], healing: [...hops[i].healing, { result: ev }] }
        : { ...hops[i], result: ev };
      next.hops = hops;
      break;
    }

    case "healing": {
      if (!next.hops.length) break;
      const hops = [...next.hops];
      const last = hops.length - 1;
      hops[last] = {
        ...hops[last],
        healing: [...hops[last].healing, { attempt: ev }],
      };
      next.hops = hops;
      break;
    }

    case "agent_hop": {
      // Why the agent chose its next step. Rendered on the connector between
      // cards - this is the visible proof of autonomy.
      if (!next.hops.length) break;
      const hops = [...next.hops];
      hops[hops.length - 1] = { ...hops[hops.length - 1], reason: ev.reason };
      next.hops = hops;
      break;
    }

    case "injection":
      next.injection = ev;
      break;

    case "token":
      next.tokens += ev.text || "";
      break;

    case "verdict":
      next.verdict = ev;
      break;

    case "error":
      next.status = "error";
      next.error = ev.message || "the agent failed";
      break;

    case "timeout":
      next.status = "error";
      next.error = `No response after ${ev.after_s}s`;
      break;

    case "done":
      // A verdict may still be missing if the run errored earlier; keep that.
      if (next.status !== "error") next.status = "done";
      break;

    default:
      break;
  }

  return next;
}
