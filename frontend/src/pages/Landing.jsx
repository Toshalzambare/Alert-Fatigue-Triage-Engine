import { useEffect, useRef, useState } from "react";
import "./landing.css";

/* The hero is the thesis: the difference between what a log search returns and
 * what an investigation concludes. We show that as a live typing sequence over
 * the real Narrative 1 chain, because the sequence IS the product. */

const CHAIN = [
  { t: "14:02", label: "60 failed logins", from: "45.133.1.88", weight: "flat" },
  { t: "14:21", label: "1 success", from: "same address", weight: "turn" },
  { t: "14:26", label: "powershell.exe", from: "vpn-gw-01", weight: "turn" },
  { t: "14:31", label: "4.2 MB outbound", from: "to 45.133.1.88", weight: "peak" },
];

function useReveal() {
  const ref = useRef(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => e.isIntersecting && setShown(true),
      { threshold: 0.25 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return [ref, shown];
}

function Chain() {
  const [step, setStep] = useState(0);
  useEffect(() => {
    if (step >= CHAIN.length) return;
    const id = setTimeout(() => setStep((s) => s + 1), step === 0 ? 500 : 900);
    return () => clearTimeout(id);
  }, [step]);

  return (
    <ol className="chain" aria-label="Investigation chain">
      {CHAIN.map((c, i) => (
        <li
          key={c.t}
          className={`chain-row ${c.weight} ${i < step ? "in" : ""}`}
          style={{ "--i": i }}
        >
          <span className="chain-time mono">{c.t}</span>
          <span className="chain-bar" aria-hidden="true">
            <i />
          </span>
          <span className="chain-label">{c.label}</span>
          <span className="chain-from mono">{c.from}</span>
        </li>
      ))}
      <li className={`chain-verdict ${step >= CHAIN.length ? "in" : ""}`}>
        <span className="eyebrow">Assessment</span>
        <p>Compromise with data exfiltration — not a failed login burst.</p>
      </li>
    </ol>
  );
}

export default function Landing({ onEnter }) {
  const [capRef, capShown] = useReveal();
  const [howRef, howShown] = useReveal();

  return (
    <div className="landing">
      <header className="nav">
        <span className="wordmark">
          Dossier<span className="wordmark-dot">.</span>
        </span>
        <nav className="nav-links">
          <a href="#capabilities">Capabilities</a>
          <a href="#pipeline">Pipeline</a>
          <button className="btn-ghost" onClick={onEnter}>
            Open console
          </button>
        </nav>
      </header>

      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Autonomous security analysis</p>
          <h1>
            Sixty failed logins
            <br />
            is <em>not the finding</em>.
          </h1>
          <p className="hero-sub">
            A search returns rows. An analyst returns a conclusion. Sentinel asks
            Elastic a question in plain English, then keeps asking — following
            each answer to the next one until it can say what actually happened.
          </p>
          <div className="hero-actions">
            <button className="btn-primary" onClick={onEnter}>
              Open console
            </button>
            <a className="btn-ghost" href="#pipeline">
              How it works
            </a>
          </div>
        </div>

        <div className="hero-panel">
          <div className="panel-head">
            <span className="live" aria-hidden="true" />
            <span className="mono">investigation · 45.133.1.88</span>
          </div>
          <Chain />
        </div>
      </section>

      <section
        className={`capabilities reveal ${capShown ? "in" : ""}`}
        id="capabilities"
        ref={capRef}
      >
        <div className="section-head">
          <p className="eyebrow">What it does</p>
          <h2>Four behaviours a search bar does not have</h2>
        </div>

        <div className="cap-grid">
          <article className="cap">
            <span className="cap-rule" aria-hidden="true" />
            <h3>Follows its own leads</h3>
            <p>
              Finds an address worth checking, checks it, finds the account it
              broke into, checks that. Up to three hops, each one chosen from
              what the last returned.
            </p>
          </article>
          <article className="cap">
            <span className="cap-rule" aria-hidden="true" />
            <h3>Recovers from empty results</h3>
            <p>
              Zero hits rarely means nothing happened. It usually means the
              username was formatted differently. Sentinel retries the shapes an
              analyst would try next.
            </p>
          </article>
          <article className="cap">
            <span className="cap-rule" aria-hidden="true" />
            <h3>Reads what it is shown</h3>
            <p>
              Drop in a phishing screenshot. It extracts the domain, spots the
              typosquat, then searches your logs for everyone who clicked it.
            </p>
          </article>
          <article className="cap">
            <span className="cap-rule" aria-hidden="true" />
            <h3>Writes rules it can prove</h3>
            <p>
              Generates a Sigma rule from what it found, runs it against 48
              hours of history, and reports the false-positive rate before you
              deploy it.
            </p>
          </article>
        </div>
      </section>

      <section
        className={`pipeline reveal ${howShown ? "in" : ""}`}
        id="pipeline"
        ref={howRef}
      >
        <div className="section-head">
          <p className="eyebrow">Pipeline</p>
          <h2>Plain English in, Elastic DSL out</h2>
        </div>

        <div className="pipe">
          <figure className="pipe-fig">
            <img
              src="https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=1000&q=75&auto=format&fit=crop"
              alt="Network switching equipment in a dimly lit server rack"
              loading="lazy"
            />
            <figcaption>
              Every query runs against a live Elastic index. Nothing is
              simulated at the data layer.
            </figcaption>
          </figure>

          <ol className="pipe-steps">
            <li>
              <span className="pipe-n mono">Ask</span>
              <div>
                <h4>You describe the concern</h4>
                <p className="mono pipe-quote">
                  “What IPs seem malicious today and why?”
                </p>
              </div>
            </li>
            <li>
              <span className="pipe-n mono">Translate</span>
              <div>
                <h4>The model calls a tool, not a database</h4>
                <p>
                  Five typed tools over MCP. The agent never writes raw DSL, so
                  a malformed query cannot reach your cluster.
                </p>
              </div>
            </li>
            <li>
              <span className="pipe-n mono">Project</span>
              <div>
                <h4>Only the fields it needs come back</h4>
                <p>
                  1,284 matches, 20 returned, 12 fields. Aggregations instead of
                  documents wherever a count will do.
                </p>
              </div>
            </li>
            <li>
              <span className="pipe-n mono">Conclude</span>
              <div>
                <h4>You get an assessment with its work shown</h4>
                <p>
                  Every hop, every query, and every retry stays on screen next
                  to the answer.
                </p>
              </div>
            </li>
          </ol>
        </div>
      </section>

      <section className="cta">
        <h2>See the reasoning, not just the answer.</h2>
        <button className="btn-primary" onClick={onEnter}>
          Open console
        </button>
      </section>

      <footer className="foot">
        <span className="mono">Sentinel</span>
        <span className="mono foot-meta">
          Gemma · LangGraph · MCP · Elastic
        </span>
      </footer>
    </div>
  );
}
