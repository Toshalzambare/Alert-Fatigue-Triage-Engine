/* Folds the flat SSE event stream into the shape the trace pane renders.
 *
 * The backend emits contract §1 events in sequence; the UI needs them grouped
 * into hops, with healing attempts nested under the call they recovered. Doing
 * that here keeps the components dumb and makes the grouping testable.
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
export function efficiencyLine(meta = {}, tool) {
  const { hits_total = 0, returned = 0, fields_returned = [], took_ms } = meta;

  // check_ip collapses documents into an aggregate - zero raw docs returned.
  if (meta.raw_documents === 0) {
    return {
      primary: `${hits_total} events → 1 profile`,
      secondary: "0 raw documents · aggregation only",
      took: took_ms,
    };
  }
  return {
    primary: `${hits_total.toLocaleString()} hits → ${returned} returned`,
    secondary: fields_returned.length ? `${fields_returned.length} fields` : null,
    took: took_ms,
  };
}

export function reduceEvent(run, ev) {
  const next = { ...run };

  switch (ev.type) {
    case "triage":
      next.triage = ev;
      break;

    case "vision":
      next.vision = ev;
      break;

    case "tool_call": {
      next.hops = [
        ...next.hops,
        {
          n: ev.hop ?? next.hops.length + 1,
          tool: ev.tool,
          args: ev.args,
          result: null,
          healing: [],
          reason: null,
          ts: ev.ts,
        },
      ];
      break;
    }

    case "tool_result": {
      const hops = [...next.hops];
      // Attach to the most recent hop for this tool. A healing retry arrives
      // as a second tool_result for the SAME hop, so it must not create one.
      for (let i = hops.length - 1; i >= 0; i--) {
        if (hops[i].tool === ev.tool || hops[i].n === ev.hop) {
          hops[i] = ev.healing
            ? { ...hops[i], healing: [...hops[i].healing, { result: ev }] }
            : { ...hops[i], result: ev };
          break;
        }
      }
      next.hops = hops;
      break;
    }

    case "healing": {
      const hops = [...next.hops];
      if (hops.length) {
        const last = hops.length - 1;
        hops[last] = {
          ...hops[last],
          healing: [...hops[last].healing, { attempt: ev }],
        };
      }
      next.hops = hops;
      break;
    }

    case "agent_hop": {
      // The reason the agent chose its next step. Rendered on the connector
      // between cards - this is the proof of autonomy.
      const hops = [...next.hops];
      if (hops.length) {
        hops[hops.length - 1] = { ...hops[hops.length - 1], reason: ev.reason };
      }
      next.hops = hops;
      break;
    }

    case "injection":
      next.injection = ev;
      break;

    case "token":
      next.tokens = next.tokens + (ev.text || "");
      break;

    case "verdict":
      next.verdict = ev;
      break;

    case "error":
      next.status = "error";
      next.error = ev.message;
      break;

    case "done":
      next.status = "done";
      break;

    default:
      break;
  }

  return next;
}
