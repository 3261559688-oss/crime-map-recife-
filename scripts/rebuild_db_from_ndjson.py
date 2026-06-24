"""从 public/api/incidents.ndjson 重建 SQLite DB
用途：当 crime_map.db 文件损坏/被清空时的灾难恢复
"""
import json, sqlite3, os

DB = "data/crime_map.db"
NDJSON = "public/api/incidents.ndjson"

if os.path.exists(DB) and os.path.getsize(DB) == 0:
    os.remove(DB)

con = sqlite3.connect(DB)
cur = con.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS dwd_intl_crime_incident_di (
    event_id TEXT PRIMARY KEY,
    title TEXT,
    description TEXT,
    news_url TEXT,
    crime_type TEXT,
    state TEXT,
    city TEXT,
    lat REAL,
    lng REAL,
    source_media TEXT,
    pub_time TEXT,
    pub_ts INTEGER,
    city_method TEXT,
    llm_a_is_crime INTEGER,
    llm_a_score INTEGER,
    llm_a_reason TEXT,
    llm_b_type TEXT,
    llm_b_score INTEGER,
    llm_b_reason TEXT,
    llm_c_state TEXT,
    llm_c_city TEXT,
    llm_c_neighbor TEXT,
    llm_c_score INTEGER,
    llm_c_reason TEXT,
    llm_c_evidence TEXT
)
""")

n = 0
with open(NDJSON, "r", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        cur.execute(
            """INSERT OR REPLACE INTO dwd_intl_crime_incident_di
            (event_id, title, news_url, crime_type, state, city, lat, lng,
             source_media, pub_time, pub_ts, city_method,
             llm_a_is_crime, llm_a_score, llm_a_reason,
             llm_b_type, llm_b_score, llm_b_reason,
             llm_c_state, llm_c_neighbor, llm_c_score, llm_c_reason, llm_c_evidence)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (d.get("id"), d.get("title"), d.get("link"),
             d.get("type"), d.get("state"), d.get("city"),
             d.get("lat"), d.get("lng"), d.get("source"),
             d.get("pub_date"), d.get("pub_ts"), d.get("city_method"),
             d.get("is_crime"), d.get("llm_score_a"), d.get("llm_a_reason"),
             d.get("type"), d.get("llm_score_b"), d.get("llm_b_reason"),
             d.get("state"), None, d.get("llm_score_c"),
             d.get("llm_c_reason"), d.get("llm_c_evidence")),
        )
        n += 1

con.commit()
print(f"✅ 重建完成：{n} 条")
print(f"   DB 大小: {os.path.getsize(DB)/1024:.1f} KB")
cur.execute(
    "SELECT SUM(CASE WHEN llm_a_is_crime IS NOT NULL THEN 1 ELSE 0 END), "
    "SUM(CASE WHEN llm_b_score IS NOT NULL THEN 1 ELSE 0 END), "
    "SUM(CASE WHEN llm_c_score IS NOT NULL THEN 1 ELSE 0 END) "
    "FROM dwd_intl_crime_incident_di"
)
a, b, c = cur.fetchone()
print(f"   LLM 覆盖：A={a} B={b} C={c}")
con.close()
