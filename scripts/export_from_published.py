#!/usr/bin/env python3
"""从展示层 incidents_published 导出 JSON 给前端"""
import sqlite3, json, os, gzip

DB = os.path.join(os.path.dirname(__file__), '..', 'data', 'crime_map.db')
OUT_FULL = os.path.join(os.path.dirname(__file__), '..', 'public', 'rss_incidents.json')
OUT_LITE = os.path.join(os.path.dirname(__file__), '..', 'public', 'rss_incidents_lite.json')
OUT_NDJSON = os.path.join(os.path.dirname(__file__), '..', 'public', 'api', 'incidents.ndjson')

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = con.execute("""
    SELECT event_id AS id, title, link, type, state, city, neighborhood,
           lat, lng, source, pub_date, pub_ts,
           llm_b_score, llm_c_score, llm_verified
    FROM incidents_published
    ORDER BY pub_ts DESC NULLS LAST
""").fetchall()

data = [dict(r) for r in rows]
# llm_verified 转 bool
for x in data:
    x['llm_verified'] = bool(x['llm_verified'])

# 写完整版
with open(OUT_FULL, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
# 写首屏精简版（最近 200 条）
with open(OUT_LITE, 'w', encoding='utf-8') as f:
    json.dump(data[:200], f, ensure_ascii=False, separators=(',', ':'))

# 写 ndjson 备份（含完整原始字段）
os.makedirs(os.path.dirname(OUT_NDJSON), exist_ok=True)
raw_rows = con.execute("""
    SELECT d.event_id AS id, d.title, d.description, d.news_url AS link,
           COALESCE(d.llm_b_type, d.crime_type) AS type,
           COALESCE(d.llm_c_state, d.state) AS state,
           COALESCE(d.llm_c_city, d.city) AS city,
           d.llm_c_neighbor AS neighborhood,
           d.lat, d.lng, d.source_media AS source,
           d.pub_time AS pub_date, d.pub_ts, d.city_method,
           d.llm_a_is_crime AS is_crime,
           d.llm_a_score AS llm_score_a, d.llm_a_reason,
           d.llm_b_score AS llm_score_b, d.llm_b_reason,
           d.llm_c_score AS llm_score_c, d.llm_c_reason, d.llm_c_evidence
    FROM dwd_intl_crime_incident_di d
""").fetchall()
with open(OUT_NDJSON, 'w', encoding='utf-8') as f:
    for r in raw_rows:
        f.write(json.dumps(dict(r), ensure_ascii=False) + '\n')

con.close()

print(f"✅ 完整版 {OUT_FULL.split('/')[-1]}: {len(data)} 条 ({os.path.getsize(OUT_FULL)/1024:.0f} KB)")
print(f"✅ 首屏版 {OUT_LITE.split('/')[-1]}: {min(200,len(data))} 条 ({os.path.getsize(OUT_LITE)/1024:.0f} KB)")
print(f"✅ ndjson 备份: {len(raw_rows)} 条 ({os.path.getsize(OUT_NDJSON)/1024:.0f} KB)")
