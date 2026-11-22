import { useOutletContext } from "react-router-dom";
import * as api from "../../api";
import { useData } from "../../hooks";
import { Kpi, Card, Badge, ErrorBox, LABEL_KIND, inr, fmtDay } from "../../components";

const RISK_COLOR = {
  Critical: "#ef4444", High: "#f97316", Medium: "#f59e0b", Low: "#10b981",
};

export default function SchedulePage() {
  const { facilityId } = useOutletContext();
  const { data, error } = useData(
    () => Promise.all([
      api.getPredictions(facilityId),
      api.getSchedule(facilityId),
      api.getFailureMetrics().catch(() => null),
    ]),
    [facilityId]
  );

  if (error) return <ErrorBox>{error}</ErrorBox>;
  if (!data) return <p>Loading...</p>;

  const [pred, sched, m] = data;
  const t = sched.totals;
  const byDay = {};
  sched.items.forEach((j) => {
    (byDay[j.recommended_date] = byDay[j.recommended_date] || []).push(j);
  });
  const days = Object.keys(byDay).sort();

  return (
    <>
      <div className="grid kpis">
        <Kpi label="Jobs scheduled" value={t.jobs} sub="next 30 days" />
        <Kpi label="Emergency jobs" value={t.emergency} sub="first planning day" />
        <Kpi label="Potential cost avoided" value={inr(t.potential_saving_rs)}
             sub="estimate, risky machines only" />
        <Kpi label="Potential downtime avoided" value={`${t.downtime_avoided_hours} h`}
             sub="estimate" />
      </div>

      <div className="grid two">
        <Card title="Failure risk by machine (next 14 days)">
          <div className="table-wrap scroll">
            <table>
              <thead>
                <tr><th>Machine</th><th>Risk</th><th>Level</th><th>Why</th></tr>
              </thead>
              <tbody>
                {pred.items.slice(0, 10).map((p) => (
                  <tr key={p.asset_id}>
                    <td>{p.asset_name}<div className="cell-sub">{p.asset_type}</div></td>
                    <td style={{ minWidth: 110 }}>
                      {p.risk_pct}%
                      <div className="riskbar">
                        <div style={{ width: `${p.risk_pct}%`, background: RISK_COLOR[p.risk_level] }} />
                      </div>
                    </td>
                    <td><Badge kind={p.risk_level}>{p.risk_level}</Badge></td>
                    <td>{p.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">Top 10 of {pred.total} machines, highest risk first.</p>
        </Card>

        <Card title="Failure prediction accuracy">
          {!m ? (
            <p className="muted">No model metrics yet. Run python predict.py.</p>
          ) : (
            <>
              <div className="metrics">
                <div className="metric"><div className="label">Precision</div>
                  <div className="value">{m.precision_pct}%</div></div>
                <div className="metric"><div className="label">Recall</div>
                  <div className="value">{m.recall_pct}%</div></div>
                <div className="metric"><div className="label">F1</div>
                  <div className="value">{m.f1_pct}%</div></div>
                <div className="metric"><div className="label">ROC-AUC</div>
                  <div className="value">{m.roc_auc}</div></div>
              </div>
              <p>
                {m.detected} of {m.test_failures} test breakdowns were warned about in
                advance, on average {m.avg_lead_days} days ahead.
              </p>
              <p className="muted">
                Random Forest, tested on {m.test_rows} unseen machine-days, with a
                {" "}{m.horizon_days}-day gap between training and test. Small simulated
                sample: promising, not proof.
              </p>
            </>
          )}
        </Card>
      </div>

      <div className="grid">
        <Card title="Maintenance calendar">
          {days.length === 0 ? (
            <p className="muted">No jobs scheduled. Run the Maintenance Agent first.</p>
          ) : (
            <div className="cal">
              {days.map((d) => (
                <div className={byDay[d].some((j) => j.priority_label === "Emergency") ? "day hot" : "day"} key={d}>
                  <h4>{fmtDay(d)} · {byDay[d].length} job(s)</h4>
                  {byDay[d].map((j) => (
                    <div className="job" key={j.schedule_id}>
                      <Badge kind={LABEL_KIND[j.priority_label]}>{j.priority_label}</Badge>
                      <span>
                        <b>{j.asset_name}</b>
                        <span className="cell-sub">{j.task}</span>
                      </span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}