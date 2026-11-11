import axios from "axios";

const api = axios.create({ baseURL: "http://localhost:8000" });
const get = (url, params) => api.get(url, { params }).then((r) => r.data);

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