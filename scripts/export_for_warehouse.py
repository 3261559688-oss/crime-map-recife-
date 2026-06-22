#!/usr/bin/env python3
"""
导出标准化数据，供数据 BP 数据接入到站内 Hive
====================================================
产出 3 套外部接口（都是公网可访问的静态文件）：

1. /api/incidents.json
   全量 JSON 数组，最新 7 天数据，结构对齐 Hive schema

2. /api/incidents.csv
   逗号分隔，UTF-8 BOM，可直接 LOAD DATA 到 Hive

3. /api/incidents.ndjson
   每行一个 JSON 对象，HDFS / Spark 标准格式（推荐）

4. /api/manifest.json
   元信息：表名/字段定义/分区/更新时间/总条数（供数据接入平台读 schema）
"""
import json
import csv
import io
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC  = ROOT / 'public' / 'rss_incidents.json'
OUT  = ROOT / 'public' / 'api'
OUT.mkdir(parents=True, exist_ok=True)

# ============================================================
# Hive 表 schema 定义（正式入仓的字段）
# ============================================================
SCHEMA = [
    # (column, hive_type, comment, source_field)
    ('event_id',      'STRING',     '事件唯一 ID',                 'id'),
    ('title',         'STRING',     '新闻标题（葡语原文）',          'title'),
    ('crime_type',    'STRING',     '犯罪类型枚举（13 类）',         'type'),
    ('crime_type_zh', 'STRING',     '犯罪类型中文',                 None),
    ('city',          'STRING',     '城市',                        'city'),
    ('state',         'STRING',     '州（2 字母）',                'state'),
    ('lat',           'DOUBLE',     '纬度',                        'lat'),
    ('lng',           'DOUBLE',     '经度',                        'lng'),
    ('source_media',  'STRING',     '来源媒体',                    'source'),
    ('news_url',      'STRING',     '原文链接',                    'link'),
    ('pub_time',      'STRING',     '发布时间 ISO',                'pub_date'),
    ('pub_ts',        'BIGINT',     '发布时间 unix 秒',            'pub_ts'),
    ('city_method',   'STRING',     '地址解析方式 (default/title/url)', 'city_method'),
    ('llm_verified',  'BOOLEAN',    'LLM 校验是否真犯罪',          'llm_verified'),
    ('llm_score',     'INT',        'LLM 置信度 0-100',           'llm_score'),
    ('llm_state',     'STRING',     'LLM 校正后的州',              'llm_state'),
    ('llm_city',      'STRING',     'LLM 校正后的城市',            'llm_city'),
    ('llm_neighbor',  'STRING',     'LLM 解析的街区',              'llm_neighbor'),
    ('llm_type',      'STRING',     'LLM 重分类的犯罪类型',        'llm_type'),
    ('etl_dt',        'STRING',     '抽取分区日期 yyyyMMdd',       None),
]

CRIME_ZH = {
    'homicidio':'凶杀','roubo':'抢劫','furto':'盗窃','estupro':'强奸',
    'trafico':'贩毒','sequestro':'绑架','violencia':'暴力','policia':'警方',
    'faccao':'派系','fraude':'诈骗','veiculo':'车辆','menor':'未成年','outros':'其他',
}

def to_record(item, etl_dt):
    """JSON 单条 → Hive 行"""
    rec = {}
    for col, _, _, src in SCHEMA:
        if col == 'crime_type_zh':
            rec[col] = CRIME_ZH.get(item.get('type',''), '')
        elif col == 'etl_dt':
            rec[col] = etl_dt
        elif src:
            rec[col] = item.get(src)
        else:
            rec[col] = None
    return rec

def main():
    with open(SRC) as f:
        data = json.load(f)

    etl_dt = datetime.now(timezone.utc).strftime('%Y%m%d')
    now_iso = datetime.now(timezone.utc).isoformat()
    records = [to_record(x, etl_dt) for x in data]

    # 1️⃣ JSON 数组（一次拉取全量）
    with open(OUT/'incidents.json','w') as f:
        json.dump(records, f, ensure_ascii=False, indent=0)

    # 2️⃣ CSV（UTF-8 BOM，逗号分隔，可直接 LOAD DATA）
    with open(OUT/'incidents.csv','w',encoding='utf-8-sig',newline='') as f:
        cols = [c[0] for c in SCHEMA]
        w = csv.DictWriter(f, fieldnames=cols, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for r in records:
            # 标题/链接里的换行 / 逗号 csv 已自动处理
            row={}
            for k,v in r.items():
                if v is None: row[k]=''
                elif isinstance(v,bool): row[k]='true' if v else 'false'
                else: row[k]=str(v).replace('\n',' ').replace('\r',' ')
            w.writerow(row)

    # 3️⃣ NDJSON（每行一个 JSON 对象，HDFS 友好）
    with open(OUT/'incidents.ndjson','w') as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False)+'\n')

    # 4️⃣ Manifest（元信息，给数据接入平台读 schema）
    manifest = {
        'table_name_suggested': 'dwd_intl_crime_incident_di',
        'business': '国际化业务-巴西-犯罪地图',
        'owner': 'dongyuhan03',
        'data_classification': 'L1-公开（巴西新闻 RSS）',
        'update_frequency': 'every 3 hours',
        'partition_strategy': 'p_date (yyyyMMdd)',
        'partition_value_now': etl_dt,
        'data_endpoints': {
            'json':   'https://crime-map-recife.vercel.app/api/incidents.json',
            'csv':    'https://crime-map-recife.vercel.app/api/incidents.csv',
            'ndjson': 'https://crime-map-recife.vercel.app/api/incidents.ndjson',
            'manifest':'https://crime-map-recife.vercel.app/api/manifest.json',
        },
        'fields': [
            {'name':c[0], 'type':c[1], 'comment':c[2]} for c in SCHEMA
        ],
        'record_count_total': len(records),
        'last_export_time': now_iso,
        'sample_records': records[:3],
    }
    with open(OUT/'manifest.json','w') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # CSV size
    import os
    print(f'✅ 导出完成 ({etl_dt} 分区)')
    print(f'   📄 JSON   : {os.path.getsize(OUT/"incidents.json"):>10,} bytes')
    print(f'   📊 CSV    : {os.path.getsize(OUT/"incidents.csv"):>10,} bytes')
    print(f'   📋 NDJSON : {os.path.getsize(OUT/"incidents.ndjson"):>10,} bytes')
    print(f'   📦 Manifest: {os.path.getsize(OUT/"manifest.json"):>10,} bytes')
    print(f'   总条数: {len(records):,}')

if __name__=='__main__':
    main()
