import { useEffect, useState } from "react";
import Console from "./pages/Console";
import Landing from "./pages/Landing";

/* Two views, no router. The console is a single destination reached from the
 * landing page - adding react-router here would be plumbing without payoff. */

export default function App() {
  const [view, setView] = useState(() =>
    window.location.hash === "#console" ? "console" : "landing"
  );

  useEffect(() => {
    const onHash = () =>
      setView(window.location.hash === "#console" ? "console" : "landing");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = (next) => {
    window.location.hash = next === "console" ? "#console" : "";
    setView(next);
    window.scrollTo(0, 0);
  };

  return view === "console" ? (
    <Console onExit={() => go("landing")} />
  ) : (
    <Landing onEnter={() => go("console")} />
  );
}
