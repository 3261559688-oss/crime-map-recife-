#!/usr/bin/env python3
"""
合并 GHA 抓到的 raw_incidents.json → SQLite raw 层（增量，按 event_id 去重）
然后报告哪些是新增的，可以喂给 LLM 跑 A/B/C。

使用：
  source .venv/bin/activate
  python scripts/merge_raw_to_db.py
"""
import json, sqlite3, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'crime_map.db')
RAW_JSON = os.path.join(ROOT, 'public', 'raw_incidents.json')


def main():
    if not os.path.exists(RAW_JSON):
        print(f'❌ {RAW_JSON} 不存在，先让 GHA 跑一次抓取，或本地跑 python scripts/fetch_all.py')
        sys.exit(1)

    raw = json.load(open(RAW_JSON, encoding='utf-8'))
    print(f'📦 raw JSON 共 {len(raw)} 条')

    con = sqlite3.connect(DB)
    cur = con.cursor()

    # 获取已有 event_id
    existing = set(r[0] for r in cur.execute('SELECT event_id FROM dwd_intl_crime_incident_di').fetchall())
    print(f'📊 当前 DB 已有 {len(existing)} 条')

    new_rows = []
    for x in raw:
        eid = x.get('id') or x.get('event_id')
        if not eid or eid in existing:
            continue
        new_rows.append((
            eid,
            x.get('title'),
            x.get('description'),
            x.get('link') or x.get('news_url'),
            x.get('type') or x.get('crime_type'),
            x.get('state'),
            x.get('city'),
            x.get('lat'),
            x.get('lng'),
            x.get('source') or x.get('source_media'),
            x.get('pub_date') or x.get('pub_time'),
            x.get('pub_ts'),
            x.get('city_method'),
        ))

    if not new_rows:
        print('✨ 无新增数据')
        con.close()
        return

    cur.executemany('''
        INSERT OR IGNORE INTO dwd_intl_crime_incident_di
        (event_id, title, description, news_url, crime_type, state, city, lat, lng,
         source_media, pub_time, pub_ts, city_method)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', new_rows)
    con.commit()

    # 报告新增中需要跑 LLM 的（A/B/C 都没有）
    need_llm = cur.execute('''
        SELECT COUNT(*) FROM dwd_intl_crime_incident_di
        WHERE llm_b_score IS NULL
    ''').fetchone()[0]

    latest = cur.execute('SELECT MAX(pub_time) FROM dwd_intl_crime_incident_di').fetchone()[0]

    print(f'✅ 新增 {len(new_rows)} 条到 raw 层')
    print(f'📅 最新日期: {latest}')
    print(f'⏳ 待跑 LLM 的: {need_llm} 条')
    print()
    print('下一步:')
    print('  1. python scripts/run_llm_pipeline.py     # 跑 A/B/C 段 LLM')
    print('  2. python scripts/refresh_published.py    # 重建展示层')
    print('  3. python scripts/export_from_published.py  # 导出前端 JSON')
    print('  4. git add public/ && git commit -m "data" && git push origin main')

    con.close()


if __name__ == '__main__':
    main()
