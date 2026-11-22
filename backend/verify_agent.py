import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))
q = lambda sql: pd.read_sql(text(sql), engine)
pd.set_option("display.width", 200)
pd.set_option("display.max_colwidth", 70)

n = q("SELECT COUNT(*) AS n FROM work_orders WHERE source LIKE 'Maintenance Agent%'").n[0]
print("work orders created by the agent:", n)
print(q("SELECT priority, COUNT(*) AS orders FROM work_orders "
        "WHERE source LIKE 'Maintenance Agent%' GROUP BY priority "
        "ORDER BY MIN(CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
        "WHEN 'medium' THEN 2 ELSE 3 END)").to_string(index=False))

print("\nMost urgent work orders:")
print(q("SELECT w.due_date, a.asset_name, a.facility_id, w.priority, w.status, w.title "
        "FROM work_orders w JOIN assets a USING(asset_id) "
        "WHERE w.source LIKE 'Maintenance Agent%' "
        "ORDER BY w.due_date, w.work_id LIMIT 5").to_string(index=False))

print("\nAlerts:")
print(q("SELECT alert_type, severity, COUNT(*) AS alerts FROM alerts "
        "WHERE source = 'Maintenance Agent' GROUP BY alert_type, severity "
        "ORDER BY MIN(CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END)")
      .to_string(index=False))

dup = q("SELECT COUNT(*) AS n FROM (SELECT asset_id FROM work_orders "
        "WHERE source LIKE 'Maintenance Agent%' GROUP BY asset_id "
        "HAVING COUNT(*) > 1) d").n[0]
print("\nmachines with more than one agent work order (should be 0):", dup)

print("\nLatest agent run:")
r = q("SELECT run_id, source, jobs, alerts, emergencies, summary "
      "FROM agent_runs WHERE agent = 'Maintenance Agent' "
      "ORDER BY run_id DESC LIMIT 1").iloc[0]
print(f"  run {r.run_id} | wording by {r.source} | {r.jobs} jobs, "
      f"{r.alerts} alerts, {r.emergencies} emergencies")
print("  summary:", r.summary)

print("\nEarlier steps' tables are intact:")
for t in ["asset_health", "equipment_events", "failure_predictions",
          "failure_model_metrics", "maintenance_schedule"]:
    print(f"  {t}: {q(f'SELECT COUNT(*) AS n FROM {t}').n[0]} rows")