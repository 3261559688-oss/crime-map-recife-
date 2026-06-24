#!/usr/bin/env python3
"""把 SQLite 两张表同步到 Parquet（数据分析用）

跑时机:
  - 每次 refresh_published.py 后跑一次
  - 跑 analytics.py 前必须先跑这个
"""
import sqlite3, pandas as pd, os

SQL_DB = "data/crime_map.db"
OUT_DIR = "data/parquet"
os.makedirs(OUT_DIR, exist_ok=True)

con = sqlite3.connect(SQL_DB)
raw = pd.read_sql("SELECT * FROM dwd_intl_crime_incident_di", con)
pub = pd.read_sql("SELECT * FROM incidents_published", con)
con.close()

raw.to_parquet(f"{OUT_DIR}/raw_incidents.parquet", index=False)
pub.to_parquet(f"{OUT_DIR}/published_incidents.parquet", index=False)

print(f"✅ raw_incidents.parquet       {len(raw):4d} 条 / {os.path.getsize(f'{OUT_DIR}/raw_incidents.parquet')/1024:.0f} KB")
print(f"✅ published_incidents.parquet {len(pub):4d} 条 / {os.path.getsize(f'{OUT_DIR}/published_incidents.parquet')/1024:.0f} KB")
