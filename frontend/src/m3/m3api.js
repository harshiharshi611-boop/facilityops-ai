// m3api.js - API calls for the Occupancy and Security pages (Milestone 3)
// Uses the same backend as the other pages. Change VITE_API_URL in frontend/.env if your API is elsewhere.
const BASE = (import.meta.env && import.meta.env.VITE_API_URL) || "http://127.0.0.1:8000";

async function get(path, params = {}) {
  const clean = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  const qs = new URLSearchParams(clean).toString();
  const res = await fetch(`${BASE}${path}${qs ? "?" + qs : ""}`);
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const j = await res.json();
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch (e) { /* keep the default message */ }
    throw new Error(msg);
  }
  return res.json();
}

export const occApi = {
  facilities: () => get("/api/occupancy/facilities"),
  summary: (f) => get("/api/occupancy/summary", { facility_id: f }),
  zones: (f) => get("/api/occupancy/zones", { facility_id: f }),
  current: (f) => get("/api/occupancy/current", { facility_id: f }),
  heatmap: (f, dayType) => get("/api/occupancy/heatmap", { facility_id: f, day_type: dayType }),
  incidents: (f) => get("/api/occupancy/incidents", { facility_id: f, limit: 20 }),
  forecast: (f, zone) => get("/api/occupancy/forecast", { facility_id: f, zone }),
  forecastMetrics: (f) => get("/api/occupancy/forecast-metrics", { facility_id: f }),
  alerts: (f) => get("/api/occupancy/alerts", { facility_id: f }),
};

export const secApi = {
  summary: (f) => get("/api/security/summary", { facility_id: f }),
  events: (f, severity) => get("/api/security/events", { facility_id: f, severity, limit: 50 }),
  eventTypes: (f) => get("/api/security/event-types", { facility_id: f }),
  timeline: (f) => get("/api/security/timeline", { facility_id: f }),
  alerts: (f) => get("/api/security/alerts", { facility_id: f }),
  visitors: (f) => get("/api/security/visitors", { facility_id: f, limit: 15 }),
  accessStats: (f) => get("/api/security/access-stats", { facility_id: f }),
  investigate: (id) => get(`/api/security/investigate/${id}`),
  evaluation: () => get("/api/security/evaluation"),
};