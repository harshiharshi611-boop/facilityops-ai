import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))
print(pd.read_sql(text("SELECT event_type, COUNT(*) FROM equipment_events GROUP BY event_type"), engine))
print(pd.read_sql(text(
    "SELECT a.asset_name, a.facility_id, e.severity, e.start_time, e.message "
    "FROM equipment_events e JOIN assets a USING(asset_id) "
    "WHERE e.event_type = 'Ongoing' ORDER BY e.peak_score DESC"), engine).to_string(index=False))