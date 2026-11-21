import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))
q = lambda sql: pd.read_sql(text(sql), engine)

print("jobs:", q("SELECT COUNT(*) AS n FROM maintenance_schedule").n[0])
print(q("SELECT priority_label, COUNT(*) AS jobs FROM maintenance_schedule "
        "GROUP BY priority_label ORDER BY MIN(CASE priority_label "
        "WHEN 'Emergency' THEN 0 WHEN 'Urgent' THEN 1 WHEN 'Planned' THEN 2 ELSE 3 END)")
      .to_string(index=False))
print()
print(q("SELECT recommended_date, asset_name, facility_id, priority_label, "
        "priority_score, task FROM maintenance_schedule "
        "WHERE priority_label <> 'Routine' "
        "ORDER BY recommended_date, priority_score DESC").to_string(index=False))
print()
print(q("SELECT COUNT(*) AS late_jobs FROM maintenance_schedule "
        "WHERE recommended_date > due_by").to_string(index=False))
print(q("SELECT SUM(potential_saving_rs) AS potential_saving_rs, "
        "SUM(downtime_avoided_hours) AS downtime_hours "
        "FROM maintenance_schedule").to_string(index=False))