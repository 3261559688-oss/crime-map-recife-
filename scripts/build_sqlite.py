#!/usr/bin/env python3
"""
落本地 SQLite 数据库
============================================================
把 public/rss_incidents.json 落到 data/crime_map.db
两张表（双层架构对齐 Hive ods + dwd）：
  - ods_intl_crime_incident_di  (原始)
  - dwd_intl_crime_incident_di  (清洗，含 LLM 字段，初始为 NULL)

用法：
  python3 scripts/build_sqlite.py        # 重建（drop & recreate）
  python3 scripts/build_sqlite.py --append  # 增量追加

之后查询：
  sqlite3 data/crime_map.db
  > SELECT state, count(*) FROM ods_intl_crime_incident_di GROUP BY state;
"""
import json
import sqlite3
import argparse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC  = ROOT / 'public' / 'rss_incidents.json'
DB   = ROOT / 'data' / 'crime_map.db'
DB.parent.mkdir(parents=True, exist_ok=True)

DDL_ODS = """
CREATE TABLE IF NOT EXISTS ods_intl_crime_incident_di (
  event_id      TEXT PRIMARY KEY,
  title         TEXT,
  crime_type    TEXT,
  city          TEXT,
  state         TEXT,
  lat           REAL,
  lng           REAL,
  source_media  TEXT,
  news_url      TEXT,
  pub_time      TEXT,
  pub_ts        INTEGER,
  city_method   TEXT,
  etl_dt        TEXT,
  p_date        TEXT,            -- 分区列
  ingested_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_ods_pdate ON ods_intl_crime_incident_di(p_date);
CREATE INDEX IF NOT EXISTS idx_ods_state ON ods_intl_crime_incident_di(state);
CREATE INDEX IF NOT EXISTS idx_ods_type  ON ods_intl_crime_incident_di(crime_type);
CREATE INDEX IF NOT EXISTS idx_ods_pubts ON ods_intl_crime_incident_di(pub_ts);
"""

DDL_DWD = """
CREATE TABLE IF NOT EXISTS dwd_intl_crime_incident_di (
  event_id      TEXT PRIMARY KEY,
  title         TEXT,
  crime_type    TEXT,
  city          TEXT,
  state         TEXT,
  lat           REAL,
  lng           REAL,
  source_media  TEXT,
  news_url      TEXT,
  pub_time      TEXT,
  pub_ts        INTEGER,
  city_method   TEXT,
  -- LLM 校验字段
  llm_verified  INTEGER,         -- 0/1/NULL
  llm_score     INTEGER,
  llm_state     TEXT,
  llm_city      TEXT,
  llm_neighbor  TEXT,
  llm_type      TEXT,
  llm_reason    TEXT,
  llm_at        TEXT,
  llm_model     TEXT,
  -- 🅰️ Stage A: 真伪
  llm_a_is_crime INTEGER,
  llm_a_score    INTEGER,
  llm_a_reason   TEXT,
  llm_a_at       TEXT,
  -- 🅱️ Stage B: 类型
  llm_b_type     TEXT,
  llm_b_score    INTEGER,
  llm_b_changed  INTEGER,
  llm_b_reason   TEXT,
  llm_b_at       TEXT,
  -- 🅲 Stage C: 地理
  llm_c_state    TEXT,
  llm_c_city     TEXT,
  llm_c_neighbor TEXT,
  llm_c_score    INTEGER,
  llm_c_evidence TEXT,
  llm_c_reason   TEXT,
  llm_c_at       TEXT,
  -- 元数据
  etl_dt        TEXT,
  p_date        TEXT,
  ingested_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_dwd_pdate    ON dwd_intl_crime_incident_di(p_date);
CREATE INDEX IF NOT EXISTS idx_dwd_verified ON dwd_intl_crime_incident_di(llm_verified);
CREATE INDEX IF NOT EXISTS idx_dwd_state    ON dwd_intl_crime_incident_di(state);
CREATE INDEX IF NOT EXISTS idx_dwd_a        ON dwd_intl_crime_incident_di(llm_a_is_crime);
CREATE INDEX IF NOT EXISTS idx_dwd_b_type   ON dwd_intl_crime_incident_di(llm_b_type);
CREATE INDEX IF NOT EXISTS idx_dwd_c_state  ON dwd_intl_crime_incident_di(llm_c_state);
"""

# 维表：城市坐标
DDL_DIM_CITY = """
CREATE TABLE IF NOT EXISTS dim_intl_crime_city_loc (
  city          TEXT PRIMARY KEY,
  state         TEXT,
  lat           REAL,
  lng           REAL,
  zoom          INTEGER,
  ingested_at   TEXT
);
"""

# 视图：方便看板用
DDL_VIEWS = """
DROP VIEW IF EXISTS v_today_state_count;
CREATE VIEW v_today_state_count AS
SELECT p_date, state, count(*) cnt
FROM dwd_intl_crime_incident_di
WHERE p_date = strftime('%Y%m%d','now')
GROUP BY p_date, state ORDER BY cnt DESC;

DROP VIEW IF EXISTS v_today_type_count;
CREATE VIEW v_today_type_count AS
SELECT p_date, crime_type, count(*) cnt
FROM dwd_intl_crime_incident_di
WHERE p_date = strftime('%Y%m%d','now')
GROUP BY p_date, crime_type ORDER BY cnt DESC;

DROP VIEW IF EXISTS v_data_quality;
CREATE VIEW v_data_quality AS
SELECT
  p_date,
  count(*) total,
  sum(CASE WHEN city_method='url' THEN 1 ELSE 0 END) url_method,
  sum(CASE WHEN city_method='title' THEN 1 ELSE 0 END) title_method,
  sum(CASE WHEN city_method='default' THEN 1 ELSE 0 END) default_method,
  sum(CASE WHEN llm_verified IS NOT NULL THEN 1 ELSE 0 END) llm_done,
  sum(CASE WHEN llm_verified=1 THEN 1 ELSE 0 END) llm_true_crime,
  sum(CASE WHEN llm_verified=0 THEN 1 ELSE 0 END) llm_not_crime
FROM dwd_intl_crime_incident_di
GROUP BY p_date;
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--append', action='store_true', help='增量追加（不 drop）')
    ap.add_argument('--db', default=str(DB))
    args = ap.parse_args()

    with open(SRC) as f:
        data = json.load(f)
    print(f'📦 读取 {len(data)} 条事件')

    db_path = Path(args.db)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    if not args.append:
        cur.executescript("""
        DROP TABLE IF EXISTS ods_intl_crime_incident_di;
        DROP TABLE IF EXISTS dwd_intl_crime_incident_di;
        DROP TABLE IF EXISTS dim_intl_crime_city_loc;
        """)
        print('🧹 已清空旧表')

    cur.executescript(DDL_ODS)
    cur.executescript(DDL_DWD)
    cur.executescript(DDL_DIM_CITY)

    now_iso = datetime.now(timezone.utc).isoformat()
    p_date  = datetime.now(timezone.utc).strftime('%Y%m%d')

    # 写 ODS
    rows_ods = []
    rows_dwd = []
    for x in data:
        base = (
            x.get('id'),
            x.get('title'),
            x.get('type'),
            x.get('city'),
            x.get('state'),
            x.get('lat'),
            x.get('lng'),
            x.get('source'),
            x.get('link'),
            x.get('pub_date'),
            x.get('pub_ts'),
            x.get('city_method'),
            p_date,
            p_date,
            now_iso,
        )
        rows_ods.append(base)

        rows_dwd.append((
            x.get('id'),
            x.get('title'),
            x.get('type'),
            x.get('city'),
            x.get('state'),
            x.get('lat'),
            x.get('lng'),
            x.get('source'),
            x.get('link'),
            x.get('pub_date'),
            x.get('pub_ts'),
            x.get('city_method'),
            None if 'llm_verified' not in x else (1 if x['llm_verified'] else 0),
            x.get('llm_score'),
            x.get('llm_state'),
            x.get('llm_city'),
            x.get('llm_neighbor'),
            x.get('llm_type'),
            x.get('llm_reason'),
            x.get('llm_at'),
            x.get('llm_model'),
            p_date, p_date, now_iso,
        ))

    cur.executemany("""
        INSERT OR REPLACE INTO ods_intl_crime_incident_di
        (event_id,title,crime_type,city,state,lat,lng,source_media,news_url,
         pub_time,pub_ts,city_method,etl_dt,p_date,ingested_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows_ods)

    cur.executemany("""
        INSERT OR REPLACE INTO dwd_intl_crime_incident_di
        (event_id,title,crime_type,city,state,lat,lng,source_media,news_url,
         pub_time,pub_ts,city_method,
         llm_verified,llm_score,llm_state,llm_city,llm_neighbor,llm_type,
         llm_reason,llm_at,llm_model,
         etl_dt,p_date,ingested_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows_dwd)

    # 写维表（如果有 cities.json）
    cities_json = ROOT/'public'/'cities.json'
    if cities_json.exists():
        cities = json.loads(cities_json.read_text())
        rows_dim = [
            (c.get('name'), c.get('state'), c.get('lat'), c.get('lng'),
             c.get('zoom'), now_iso)
            for c in (cities if isinstance(cities,list) else cities.get('cities',[]))
        ]
        cur.executemany("""
            INSERT OR REPLACE INTO dim_intl_crime_city_loc
            (city,state,lat,lng,zoom,ingested_at) VALUES (?,?,?,?,?,?)
        """, rows_dim)
        print(f'✅ 维表 dim_intl_crime_city_loc: {len(rows_dim)} 条')

    cur.executescript(DDL_VIEWS)
    conn.commit()

    # 摘要
    print('\n========== 落库完成 ==========')
    cur.execute('SELECT count(*) FROM ods_intl_crime_incident_di'); print(f'  ods 表条数: {cur.fetchone()[0]:,}')
    cur.execute('SELECT count(*) FROM dwd_intl_crime_incident_di'); print(f'  dwd 表条数: {cur.fetchone()[0]:,}')
    cur.execute('SELECT count(*) FROM dim_intl_crime_city_loc'); print(f'  dim 表条数: {cur.fetchone()[0]:,}')

    print('\n📊 各州 TOP 5（ods）：')
    cur.execute('SELECT state,count(*) FROM ods_intl_crime_incident_di GROUP BY state ORDER BY 2 DESC LIMIT 5')
    for s,c in cur.fetchall(): print(f'    {s or "(NULL)":8} {c:>5}')

    print('\n📊 各类型 TOP 5（ods）：')
    cur.execute('SELECT crime_type,count(*) FROM ods_intl_crime_incident_di GROUP BY crime_type ORDER BY 2 DESC LIMIT 5')
    for t,c in cur.fetchall(): print(f'    {t or "(NULL)":12} {c:>5}')

    print('\n📊 数据质量监控视图 v_data_quality：')
    cur.execute('SELECT * FROM v_data_quality')
    cols = [d[0] for d in cur.description]
    for row in cur.fetchall():
        print('   ', dict(zip(cols,row)))

    print(f'\n✅ 数据库文件已生成: {db_path}')
    print(f'   大小: {db_path.stat().st_size:,} bytes')
    print('\n🔍 查询示例:')
    print(f'    sqlite3 {db_path}')
    print('    > SELECT * FROM v_today_state_count;')
    print('    > SELECT * FROM v_data_quality;')

    conn.close()

if __name__=='__main__':
    main()
