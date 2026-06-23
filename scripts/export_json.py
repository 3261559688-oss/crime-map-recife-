#!/usr/bin/env python3
"""
从 SQLite (dwd 表) 导出前端用的 incidents.json
============================================
用法：
    python3 scripts/export_json.py
    python3 scripts/export_json.py --only-clean    # 仅导 LLM 真犯罪
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data/crime_map.db')

def export(only_clean=False, db_path=DB):
    if not os.path.exists(db_path):
        print(f"❌ DB 不存在: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 查询：LLM 字段优先，原值兜底
    where = ""
    if only_clean:
        where = "WHERE llm_a_is_crime = 1"

    rows = conn.execute(f"""
        SELECT
            event_id AS id,
            title,
            description,
            news_url AS link,
            COALESCE(llm_b_type, crime_type) AS type,
            COALESCE(llm_c_state, state) AS state,
            COALESCE(llm_c_city, city) AS city,
            llm_c_neighbor AS neighborhood,
            lat, lng,
            source_media AS source,
            pub_time AS pub_date,
            pub_ts,
            city_method,
            llm_a_is_crime AS is_crime,
            llm_a_score AS llm_score_a,
            llm_b_score AS llm_score_b,
            llm_c_score AS llm_score_c,
            llm_a_reason,
            llm_b_reason,
            llm_c_reason,
            llm_c_evidence
        FROM dwd_intl_crime_incident_di
        {where}
        ORDER BY pub_ts DESC
    """).fetchall()

    items = []
    for r in rows:
        d = dict(r)
        # 清理 None 字段
        d = {k: v for k, v in d.items() if v is not None and v != ''}
        items.append(d)

    # 1) 主用 incidents.json (兼容前端旧格式)
    out1 = os.path.join(ROOT, 'public/rss_incidents.json')
    with open(out1, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False)

    # 2) 标准 API (含 meta)
    out2 = os.path.join(ROOT, 'public/api/incidents.json')
    os.makedirs(os.path.dirname(out2), exist_ok=True)
    with open(out2, 'w', encoding='utf-8') as f:
        json.dump({
            'updated_at': datetime.now().isoformat(),
            'count': len(items),
            'incidents': items,
        }, f, ensure_ascii=False)

    # 3) NDJSON (流式)
    out3 = os.path.join(ROOT, 'public/api/incidents.ndjson')
    with open(out3, 'w', encoding='utf-8') as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + '\n')

    # 统计
    real = sum(1 for x in items if x.get('is_crime') == 1)
    with_b = sum(1 for x in items if x.get('type') and x.get('llm_score_b'))
    with_c = sum(1 for x in items if x.get('llm_score_c'))

    print(f"""
✅ 导出完成
═════════════════════════════════
📦 总条数：       {len(items)}
🅰️ A 段真犯罪：    {real}
🅱️ B 段已分类：    {with_b}
🅲 C 段已重判：    {with_c}
═════════════════════════════════
📁 文件：
  - public/rss_incidents.json   ({os.path.getsize(out1)//1024} KB)
  - public/api/incidents.json
  - public/api/incidents.ndjson
""")

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--only-clean', action='store_true', help='只导 LLM 真犯罪')
    ap.add_argument('--db', default=DB)
    args = ap.parse_args()
    export(args.only_clean, args.db)
