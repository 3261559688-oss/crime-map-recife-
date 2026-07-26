#!/usr/bin/env python3
"""
临时前端导出：LLM catch-up 前，优先保证线上有最近 7 天数据。

口径：
- 来源：dwd_intl_crime_incident_di 原始/清洗层
- 最近 7 天
- 必须有 lat/lng
- 必须有 city/state
- 不强制 llm_a_is_crime=1
- 保留 llm_verified 字段，标记是否已经通过 LLM A 严格确认

注意：这是临时过渡口径。LLM self-hosted runner 稳定后，应切回 export_from_published.py。
"""
import json
import os
import sqlite3
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'crime_map.db')
OUT_FULL = os.path.join(ROOT, 'public', 'rss_incidents.json')
OUT_LITE = os.path.join(ROOT, 'public', 'rss_incidents_lite.json')
OUT_NDJSON = os.path.join(ROOT, 'public', 'api', 'incidents.ndjson')
OUT_META = os.path.join(ROOT, 'public', 'meta.json')

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = con.execute("""
SELECT
  event_id AS id,
  title,
  news_url AS link,
  COALESCE(llm_b_type, crime_type) AS type,
  COALESCE(llm_c_state, state) AS state,
  COALESCE(llm_c_city, city) AS city,
  llm_c_neighbor AS neighborhood,
  lat, lng,
  source_media AS source,
  pub_time AS pub_date,
  pub_ts,
  llm_b_score,
  llm_c_score,
  CASE WHEN llm_a_is_crime = 1 THEN 1 ELSE 0 END AS llm_verified
FROM dwd_intl_crime_incident_di
WHERE pub_ts >= strftime('%s','now','-7 days')
  AND lat IS NOT NULL AND lng IS NOT NULL
  AND COALESCE(llm_c_city, city) IS NOT NULL
  AND COALESCE(llm_c_state, state) IS NOT NULL
ORDER BY pub_ts DESC
""").fetchall()

data = []
for r in rows:
    x = {k: r[k] for k in r.keys() if r[k] is not None and r[k] != ''}
    x['llm_verified'] = bool(x.get('llm_verified'))
    data.append(x)

os.makedirs(os.path.dirname(OUT_NDJSON), exist_ok=True)
with open(OUT_FULL, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
with open(OUT_LITE, 'w', encoding='utf-8') as f:
    json.dump(data[:200], f, ensure_ascii=False, separators=(',', ':'))
with open(OUT_NDJSON, 'w', encoding='utf-8') as f:
    for x in data:
        f.write(json.dumps(x, ensure_ascii=False) + '\n')
with open(OUT_META, 'w', encoding='utf-8') as f:
    json.dump({
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'count': len(data),
        'latest': data[0].get('pub_date') if data else None,
        'mode': 'raw_7d_unverified_until_llm_ready',
        'llm_verified_count': sum(1 for x in data if x.get('llm_verified') is True),
        'note': 'Temporary frontend export: raw 7d with geo/city/state until LLM self-hosted runner catch-up is ready.'
    }, f, ensure_ascii=False, separators=(',', ':'))

con.close()
print(f"✅ raw 7d frontend export: {len(data)} incidents")
print(f"   latest: {data[0].get('pub_date') if data else '?'}")
print(f"   llm_verified: {sum(1 for x in data if x.get('llm_verified') is True)}")
