// m3components.jsx - small building blocks for the Occupancy and Security pages
import React from "react";
import "./m3.css";

export function KpiCard({ label, value, sub, tone = "navy" }) {
  return (
    <div className={`m3-kpi m3-tone-${tone}`}>
      <div className="m3-kpi-label">{label}</div>
      <div className="m3-kpi-value">{value}</div>
      {sub ? <div className="m3-kpi-sub">{sub}</div> : null}
    </div>
  );
}

export function Panel({ title, note, right, children }) {
  return (
    <section className="m3-panel">
      <div className="m3-panel-head">
        <h3>{title}</h3>
        {right ? <div className="m3-panel-right">{right}</div> : null}
      </div>
      {note ? <p className="m3-note">{note}</p> : null}
      {children}
    </section>
  );
}

export function SeverityBadge({ severity }) {
  return <span className={`m3-badge m3-sev-${String(severity).toLowerCase()}`}>{severity}</span>;
}

export function StatusBadge({ status }) {
  const cls = String(status).toLowerCase().replace(/[^a-z]+/g, "-");
  return <span className={`m3-badge m3-st-${cls}`}>{status}</span>;
}

export function Loading({ text = "Loading..." }) {
  return <div className="m3-loading">{text}</div>;
}

export function ErrorBox({ message }) {
  return <div className="m3-error">Could not load this part: {message}</div>;
}

// Shows loading / error, otherwise calls children(data)
export function Async({ state, children }) {
  if (state.loading) return <Loading />;
  if (state.error) return <ErrorBox message={state.error} />;
  return children(state.data);
}

export function DataTable({ columns, rows, empty = "Nothing to show." }) {
  if (!rows || rows.length === 0) return <div className="m3-empty">{empty}</div>;
  return (
    <div className="m3-scroll">
      <table className="m3-table">
        <thead>
          <tr>{columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => <td key={c.key}>{c.render ? c.render(r) : r[c.key] ?? "-"}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function BarList({ items, max = 100, unit = "%" }) {
  return (
    <div className="m3-bars">
      {items.map((it) => (
        <div className="m3-bar-row" key={it.label}>
          <div className="m3-bar-label">{it.label}</div>
          <div className="m3-bar-track">
            <div className="m3-bar-fill" style={{ width: `${Math.min(100, (it.value / max) * 100)}%`, background: it.color || "var(--m3-teal)" }} />
          </div>
          <div className="m3-bar-value">{it.text ?? `${it.value}${unit}`}</div>
        </div>
      ))}
    </div>
  );
}

const STOPS = [[0, [238, 246, 246]], [0.5, [42, 157, 143]], [0.9, [244, 162, 97]], [1.1, [209, 73, 91]]];
export function heatColor(pct) {
  const t = Math.max(0, Math.min(pct, 120)) / 100;
  for (let i = 1; i < STOPS.length; i++) {
    if (t <= STOPS[i][0]) {
      const [t0, c0] = STOPS[i - 1];
      const [t1, c1] = STOPS[i];
      const k = (t - t0) / (t1 - t0);
      const rgb = c0.map((v, j) => Math.round(v + (c1[j] - v) * k));
      return `rgb(${rgb.join(",")})`;
    }
  }
  return `rgb(${STOPS[STOPS.length - 1][1].join(",")})`;
}

export function Heatmap({ data }) {
  return (
    <div className="m3-scroll">
      <div className="m3-heat" style={{ gridTemplateColumns: `130px repeat(${data.hours.length}, minmax(18px, 1fr))` }}>
        <div />
        {data.hours.map((h) => <div key={h} className="m3-heat-hour">{h % 3 === 0 ? h : ""}</div>)}
        {data.zones.map((z, zi) => (
          <React.Fragment key={z}>
            <div className="m3-heat-zone">{z}</div>
            {data.values[zi].map((v, hi) => (
              <div key={hi} className="m3-heat-cell" style={{ background: heatColor(v) }} title={`${z} ${data.hours[hi]}:00 - ${v}% full`} />
            ))}
          </React.Fragment>
        ))}
      </div>
      <div className="m3-legend">
        <span>0% empty</span>
        <span className="m3-legend-bar" />
        <span>100%+ full</span>
      </div>
    </div>
  );
}

// Simple SVG line chart. series: [{name, color, dashed, values:[number|null,...]}]
export function LineChart({ series, height = 220, hline, xTicks = [] }) {
  const W = 700, H = height, pad = { l: 40, r: 10, t: 10, b: 24 };
  const n = Math.max(...series.map((s) => s.values.length), 2);
  const all = series.flatMap((s) => s.values.filter((v) => v !== null && v !== undefined));
  const max = Math.max(1, ...all, hline ? hline.value : 0) * 1.1;
  const x = (i) => pad.l + (i / (n - 1)) * (W - pad.l - pad.r);
  const y = (v) => pad.t + (1 - v / max) * (H - pad.t - pad.b);
  const pathFor = (values) => {
    let d = "", pen = false;
    values.forEach((v, i) => {
      if (v === null || v === undefined) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)} `;
      pen = true;
    });
    return d.trim();
  };
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="m3-chart" role="img">
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={pad.l} x2={W - pad.r} y1={y(max / 1.1 * f)} y2={y(max / 1.1 * f)} className="m3-grid" />
            <text x={pad.l - 6} y={y(max / 1.1 * f) + 4} className="m3-axis" textAnchor="end">{Math.round(max / 1.1 * f)}</text>
          </g>
        ))}
        {xTicks.map((t) => (
          <text key={t.i} x={x(t.i)} y={H - 6} className="m3-axis" textAnchor="middle">{t.label}</text>
        ))}
        {hline ? (
          <g>
            <line x1={pad.l} x2={W - pad.r} y1={y(hline.value)} y2={y(hline.value)} stroke="var(--m3-amber)" strokeDasharray="5 4" strokeWidth="1.5" />
            <text x={W - pad.r} y={y(hline.value) - 4} className="m3-axis" textAnchor="end">{hline.label}</text>
          </g>
        ) : null}
        {series.map((s) => (
          <path key={s.name} d={pathFor(s.values)} fill="none" stroke={s.color} strokeWidth="2"
            strokeDasharray={s.dashed ? "4 3" : undefined} />
        ))}
      </svg>
      <div className="m3-legend">
        {series.map((s) => (
          <span key={s.name} className="m3-legend-item"><i style={{ background: s.color }} />{s.name}</span>
        ))}
      </div>
    </div>
  );
}