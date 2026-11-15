import { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import * as api from "../api";
import { Card, inr } from "../components";

export default function AgentPage() {
  const { facilityId } = useOutletContext();
  const [recs, setRecs] = useState(null);
  const [agentRun, setAgentRun] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    setAgentRun(null);
    setRecs(null);
    api.getRecs(facilityId)
      .then(setRecs)
      .catch(() => setError("Cannot reach the API. Is uvicorn running on port 8000?"));
  }, [facilityId]);

  const runAgent = async () => {
    setRunning(true);
    setError("");
    try {
      setAgentRun(await api.runAgent(facilityId));
      setRecs(await api.getRecs(facilityId));
    } catch {
      setError("Agent run failed. Check the uvicorn terminal for the error.");
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      {error && <div className="error">{error}</div>}

      <div className="grid">
        <Card title="Energy Agent">
          <p className="muted">
            Runs the LangGraph workflow: load, validate, detect, analyze,
            recommend, save.
          </p>
          <button className="primary" onClick={runAgent} disabled={running}>
            {running ? "Agent running..." : "Run Energy Agent"}
          </button>
          {agentRun && (
            <>
              <p className="muted">Finished. Source: {agentRun.source}</p>
              <ol className="steps">
                {agentRun.steps.map((s, i) => <li key={i}>{s}</li>)}
              </ol>
            </>
          )}
        </Card>
      </div>

      <div className="grid">
        <Card title="AI recommendations">
          {!recs ? (
            <p className="muted">Loading...</p>
          ) : recs.items.length === 0 ? (
            <p className="muted">No recommendations yet. Click "Run Energy Agent".</p>
          ) : (
            recs.items.map((r, i) => (
              <div className="rec" key={i}>
                <div className="rec-title">
                  <span className={`badge ${r.priority}`}>{r.priority}</span>
                  {r.title}
                </div>
                <p>{r.detail}</p>
                {Number(r.est_saving_rs) > 0 && (
                  <div className="saving">
                    Estimated saving: {inr(Math.round(r.est_saving_rs))} per month
                  </div>
                )}
              </div>
            ))
          )}
        </Card>
      </div>
    </>
  );
}