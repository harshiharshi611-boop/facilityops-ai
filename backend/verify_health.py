import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))
print(pd.read_sql(text("SELECT status, COUNT(*) FROM asset_health GROUP BY status"), engine))
print(pd.read_sql(text("SELECT asset_name, facility_id, health_score, status, main_issue "
                       "FROM asset_health ORDER BY health_score LIMIT 8"), engine).to_string(index=False))