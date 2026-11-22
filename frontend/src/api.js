import axios from "axios";

const api = axios.create({ baseURL: "http://localhost:8000" });
const get = (url, params) => api.get(url, { params }).then((r) => r.data);

// ---------- Energy (Milestone 1) ----------
export const getFacilities = () => get("/facilities");
export const getSummary = (id) => get("/energy/summary", { facility_id: id });
export const getTrends = (id) => get("/energy/trends", { facility_id: id });
export const getAnomalies = (id) =>
  get("/energy/anomalies", { facility_id: id, limit: 10 });
export const getRecs = (id) =>
  get("/energy/recommendations", { facility_id: id });
export const getMetrics = () => get("/energy/model-metrics");
export const runAgent = (id) =>
  api.post("/energy/agent/run", null, { params: { facility_id: id } })
     .then((r) => r.data);

// ---------- Maintenance (Milestone 2) ----------
export const getMaintSummary = (id) => get("/maintenance/summary", { facility_id: id });
export const getMaintAssets = (id) => get("/maintenance/assets", { facility_id: id });
export const getHealthByType = (id) => get("/maintenance/health-by-type", { facility_id: id });
export const getMaintEvents = (id) =>
  get("/maintenance/events", { facility_id: id, event_type: "Ongoing" });
export const getPredictions = (id) => get("/maintenance/predictions", { facility_id: id });
export const getFailureMetrics = () => get("/maintenance/model-metrics");
export const getSchedule = (id) => get("/maintenance/schedule", { facility_id: id });
export const getMaintAlerts = (id) => get("/maintenance/alerts", { facility_id: id });
export const getWorkOrders = (id) => get("/maintenance/work-orders", { facility_id: id });
export const getLastRun = () => get("/maintenance/agent/last-run");
export const runMaintAgent = () =>
  api.post("/maintenance/agent/run").then((r) => r.data);

// shows the API's own message (for example "Missing table(s): ...") when there is one
export const errorText = (e, fallback) => e?.response?.data?.detail || fallback;