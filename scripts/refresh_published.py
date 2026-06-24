#!/usr/bin/env python3
"""
刷新展示层 incidents_published
从原始层 dwd_intl_crime_incident_di 重新过滤生成

跑这个的时机：
  - LLM 跑完一批后
  - 改了过滤规则后
  - 抓取了新数据后
"""
import sqlite3, os, sys

DB = os.path.join(os.path.dirname(__file__), '..', 'data', 'crime_map.db')
con = sqlite3.connect(DB)
cur = con.cursor()

# 备份当前展示层数量（方便对比）
old = cur.execute("SELECT COUNT(*) FROM incidents_published").fetchone()[0]

# 重建展示层
cur.execute("DELETE FROM incidents_published")
cur.execute("""
INSERT INTO incidents_published (
    event_id, title, link, type, state, city, neighborhood,
    lat, lng, source, pub_date, pub_ts,
    llm_b_score, llm_c_score, llm_verified
)
SELECT
    event_id, title, news_url AS link,
    COALESCE(llm_b_type, crime_type) AS type,
    COALESCE(llm_c_state, state) AS state,
    COALESCE(llm_c_city, city) AS city,
    llm_c_neighbor AS neighborhood,
    lat, lng, source_media, pub_time, pub_ts,
    llm_b_score, llm_c_score,
    CASE WHEN llm_b_score IS NOT NULL THEN 1 ELSE 0 END
FROM dwd_intl_crime_incident_di
WHERE
    (llm_a_is_crime = 1 OR llm_a_is_crime IS NULL)
    AND lat IS NOT NULL AND lng IS NOT NULL
    AND COALESCE(llm_c_city, city) IS NOT NULL
    AND COALESCE(llm_c_state, state) IS NOT NULL
""")
new = cur.execute("SELECT COUNT(*) FROM incidents_published").fetchone()[0]
con.commit()

# 统计
total_raw = cur.execute("SELECT COUNT(*) FROM dwd_intl_crime_incident_di").fetchone()[0]
verified = cur.execute("SELECT COUNT(*) FROM incidents_published WHERE llm_verified=1").fetchone()[0]
with_neighbor = cur.execute("SELECT COUNT(*) FROM incidents_published WHERE neighborhood IS NOT NULL").fetchone()[0]

print(f"📊 原始层: {total_raw} 条")
print(f"📊 展示层: {old} → {new} 条 ({'+' if new>=old else ''}{new-old})")
print(f"   ├─ LLM 校验: {verified} 条 ({verified/new*100:.0f}%)")
print(f"   └─ 含街区:   {with_neighbor} 条 ({with_neighbor/new*100:.0f}%)")
con.close()
