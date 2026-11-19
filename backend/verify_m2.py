import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))

queries = {
    "assets": "SELECT COUNT(*) FROM assets",
    "scenarios": "SELECT scenario, COUNT(*) FROM asset_scenarios GROUP BY scenario",
    "maintenance": "SELECT maintenance_type, COUNT(*) FROM maintenance_records GROUP BY maintenance_type",
    "sensor rows": "SELECT COUNT(*) FROM sensor_readings",
    "energy_usage (Milestone 1)": "SELECT COUNT(*) FROM energy_usage",
}
for name, sql in queries.items():
    print("\n" + name)
    print(pd.read_sql(text(sql), engine).to_string(index=False))