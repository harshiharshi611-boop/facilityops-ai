import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import * as api from "../../api";
import { useData } from "../../hooks";
import { Card, Badge, ErrorBox, fmtDay } from "../../components";

const PRIORITIES = ["All", "critical", "high", "medium", "low"];

export default function WorkOrdersPage() {
  const { facilityId } = useOutletContext();
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState(null);
  const [runError, setRunError] = useState("");
  const [priority, setPriority] = useState("All");

  const { data, error, reload } = useData(
    () => Promise.all([
      api.getMaintAlerts(facilityId),
      api.getWorkOrders(facilityId),
      api.getLastRun(),
    ]),
    [facilityId]
  );

  const runAgent = async () => {
    setRunning(true);
    setRunError("");
    try {
      setRunResult(await api.runMaintAgent());
      await reload();
    } catch (e) {
      setRunError(api.errorText(e, "The agent run failed. Check the uvicorn terminal."));
    } finally {
      setRunning(false);
    }
  };

  const last = data ? data[2].run : null;
  const summaryText = runResult ? runResult.summary : last ? last.summary : null;

  const agentCard = (
    <Card title="Maintenance Agent">
      <p className="muted">
        Runs the 9-step LangGraph workflow for all facilities: load, validate, score
        health, detect, predict, plan, explain, create tickets, save. It replaces the
        agent's earlier work orders and alerts.
      </p>
      <button className="primary" onClick={runAgent} disabled={running}>
        {running ? "Agent running..." : "Run Maintenance Agent"}
      </button>
      {runError && <div className="error" style={{ marginTop: 12 }}>{runError}</div>}
      {summaryText && <p>{summaryText}</p>}
      {runResult ? (
        <>
          <p className="muted">
            Finished. Wording by {runResult.source}: {runResult.jobs} work orders,{" "}
            {runResult.alerts} alerts.
          </p>
          <ol className="steps">
            {runResult.steps.map((s, i) => <li key={i}>{s}</li>)}
          </ol>
        </>
      ) : last ? (
        <p className="muted">
          Last run #{last.run_id} at {last.finished_at}: {last.jobs} work orders,{" "}
          {last.alerts} alerts, wording by {last.source}.
        </p>
      ) : (
        <p className="muted">The agent has not run yet. Click the button.</p>
      )}
    </Card>
  );

  if (error) {
    return (
      <>
        <ErrorBox>{error}</ErrorBox>
        <div className="grid">{agentCard}</div>
      </>
    );
  }
  if (!data) return <p>Loading...</p>;

  const [alerts, orders] = data;
  const rows = priority === "All"
    ? orders.items
    : orders.items.filter((w) => w.priority === priority);

  return (
    <>
      <div className="grid">{agentCard}</div>

      <div className="grid">
        <Card title={`Alerts (${alerts.total})`}>
          {alerts.items.length === 0 ? (
            <p className="muted">No open alerts.</p>
          ) : (
            alerts.items.map((a) => (
              <div className="list-row" key={a.alert_id}>
                <Badge kind={a.severity}>{a.severity}</Badge>
                <div>
                  <b>{a.title}</b>
                  <div className="cell-sub">{a.message}</div>
                  <div className="cell-sub">Notify: {a.notify}</div>
                </div>
              </div>
            ))
          )}
          <p className="muted">
            Alerts are recorded here. Email, SMS and Slack delivery comes in a later milestone.
          </p>
        </Card>
      </div>

      <div className="grid">
        <Card title={`Work orders (${rows.length})`}>
          <div className="filters">
            {PRIORITIES.map((p) => (
              <button key={p} className={priority === p ? "chip on" : "chip"}
                      onClick={() => setPriority(p)}>{p}</button>
            ))}
          </div>
          <div className="table-wrap scroll">
            <table>
              <thead>
                <tr><th>Due</th><th>Machine</th><th>Priority</th><th>Task</th><th>Status</th></tr>
              </thead>
              <tbody>
                {rows.map((w) => (
                  <tr key={w.work_id}>
                    <td>{fmtDay(w.due_date)}</td>
                    <td>{w.asset_name}<div className="cell-sub">{w.asset_type}</div></td>
                    <td><Badge kind={w.priority}>{w.priority}</Badge></td>
                    <td>
                      {w.title}
                      <div className="cell-sub">{w.description}</div>
                    </td>
                    <td>{w.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  );
}