export const inr = (n) => "₹" + Number(n).toLocaleString("en-IN");

export function Kpi({ label, value, sub }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      <div className="sub">{sub}</div>
    </div>
  );
}

export function Card({ title, children }) {
  return (
    <div className="card">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

// schedule labels share the badge colours used for severities
export const LABEL_KIND = {
  Emergency: "critical", Urgent: "high", Planned: "medium", Routine: "low",
};

export function Badge({ kind, children }) {
  return <span className={`badge ${String(kind).toLowerCase()}`}>{children}</span>;
}

export function ErrorBox({ children }) {
  return <div className="error">{children}</div>;
}

// "2026-10-30" -> "Fri, 30 Oct"
export function fmtDay(iso) {
  const d = new Date(String(iso).slice(0, 10) + "T00:00:00");
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short" });
}