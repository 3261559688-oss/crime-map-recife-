#!/usr/bin/env python3
"""
导出双层数仓数据，供站内数据 BP 接入到 Hive
============================================================
产出 2 套接口（ods + dwd），按数仓规范分层：

  ods_intl_crime_incident_di    ← 原始表（RSS 直出）
     ├── /api/ods/incidents.ndjson
     ├── /api/ods/incidents.csv
     └── /api/ods/manifest.json

  dwd_intl_crime_incident_di    ← 清洗表（含 LLM 校验字段）
     ├── /api/dwd/incidents.ndjson
     ├── /api/dwd/incidents.csv
     └── /api/dwd/manifest.json
"""
import json
import csv
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC  = ROOT / 'public' / 'rss_incidents.json'
OUT_ODS = ROOT / 'public' / 'api' / 'ods'
OUT_DWD = ROOT / 'public' / 'api' / 'dwd'
OUT_ODS.mkdir(parents=True, exist_ok=True)
OUT_DWD.mkdir(parents=True, exist_ok=True)

# ============================================================
# ODS 表 schema（原始字段，不含 LLM）
# ============================================================
SCHEMA_ODS = [
    ('event_id',     'STRING', '事件唯一 ID',          'id'),
    ('title',        'STRING', '新闻标题（葡语原文）',   'title'),
    ('crime_type',   'STRING', '关键词预分类',         'type'),
    ('city',         'STRING', '关键词解析城市',       'city'),
    ('state',        'STRING', '州（2 字母）',         'state'),
    ('lat',          'DOUBLE', '纬度',                'lat'),
    ('lng',          'DOUBLE', '经度',                'lng'),
    ('source_media', 'STRING', '来源媒体',            'source'),
    ('news_url',     'STRING', '原文链接',            'link'),
    ('pub_time',     'STRING', '发布时间 ISO',        'pub_date'),
    ('pub_ts',       'BIGINT', '发布时间 unix 秒',    'pub_ts'),
    ('city_method',  'STRING', '解析方式 (default/title/url)', 'city_method'),
    ('etl_dt',       'STRING', '抽取分区 yyyyMMdd',   None),
]

# ============================================================
# DWD 表 schema（ods 全字段 + LLM 校验字段）
# ============================================================
SCHEMA_DWD = SCHEMA_ODS[:-1] + [   # 去掉 etl_dt（最后再加）
    ('llm_verified', 'BOOLEAN', 'LLM 校验是否真犯罪',     'llm_verified'),
    ('llm_score',    'INT',     'LLM 置信度 0-100',       'llm_score'),
    ('llm_state',    'STRING',  'LLM 校正后的州',         'llm_state'),
    ('llm_city',     'STRING',  'LLM 校正后的城市',        'llm_city'),
    ('llm_neighbor', 'STRING',  'LLM 解析的街区',          'llm_neighbor'),
    ('llm_type',     'STRING',  'LLM 重分类的犯罪类型',     'llm_type'),
    ('llm_reason',   'STRING',  'LLM 判定理由',            'llm_reason'),
    ('llm_at',       'STRING',  'LLM 校验时间戳',          'llm_at'),
    ('llm_model',    'STRING',  '使用的 LLM 模型',         'llm_model'),
    ('etl_dt',       'STRING',  '抽取分区 yyyyMMdd',      None),
]

CRIME_ZH = {
    'homicidio':'凶杀','roubo':'抢劫','furto':'盗窃','estupro':'强奸',
    'trafico':'贩毒','sequestro':'绑架','violencia':'暴力','policia':'警方',
    'faccao':'派系','fraude':'诈骗','veiculo':'车辆','menor':'未成年','outros':'其他',
}

def to_record(item, schema, etl_dt):
    rec = {}
    for col, _, _, src in schema:
        if col == 'etl_dt':
            rec[col] = etl_dt
        elif src:
            rec[col] = item.get(src)
        else:
            rec[col] = None
    return rec

def write_files(records, out_dir, schema, table_name, comment, has_llm):
    # NDJSON
    with open(out_dir/'incidents.ndjson','w') as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False)+'\n')
    # CSV
    with open(out_dir/'incidents.csv','w',encoding='utf-8-sig',newline='') as f:
        cols = [c[0] for c in schema]
        w = csv.DictWriter(f, fieldnames=cols, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for r in records:
            row={}
            for k,v in r.items():
                if v is None: row[k]=''
                elif isinstance(v,bool): row[k]='true' if v else 'false'
                else: row[k]=str(v).replace('\n',' ').replace('\r',' ')
            w.writerow(row)
    # JSON 数组
    with open(out_dir/'incidents.json','w') as f:
        json.dump(records, f, ensure_ascii=False, indent=0)
    # Manifest
    base='https://crime-map-recife.vercel.app/api/'+out_dir.name
    manifest = {
        'table_name': table_name,
        'comment': comment,
        'layer': 'ods' if 'ods' in table_name else 'dwd',
        'has_llm_fields': has_llm,
        'business': '国际化业务-巴西-犯罪地图',
        'owner': 'dongyuhan03',
        'data_classification': 'L1-公开（巴西新闻 RSS）',
        'update_frequency': 'every 30 minutes (Vercel) / hourly pull recommended',
        'partition_strategy': 'p_date STRING (yyyyMMdd)',
        'partition_value_now': records[0]['etl_dt'] if records else '',
        'data_endpoints': {
            'json':   f'{base}/incidents.json',
            'csv':    f'{base}/incidents.csv',
            'ndjson': f'{base}/incidents.ndjson',
            'manifest': f'{base}/manifest.json',
        },
        'fields': [{'name':c[0],'type':c[1],'comment':c[2]} for c in schema],
        'record_count_total': len(records),
        'last_export_time': datetime.now(timezone.utc).isoformat(),
        'sample_records': records[:3],
    }
    with open(out_dir/'manifest.json','w') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

def main():
    with open(SRC) as f: data = json.load(f)
    etl_dt = datetime.now(timezone.utc).strftime('%Y%m%d')

    # ODS：所有原始数据
    ods = [to_record(x, SCHEMA_ODS, etl_dt) for x in data]
    # DWD：只导出已经过 LLM 校验的（or 全量含 null，看你需要）
    # 这里采用"全量 + LLM 字段（可能为 null）"，这样 DWD 跟 ODS 1:1，方便 BP 看
    dwd = [to_record(x, SCHEMA_DWD, etl_dt) for x in data]

    write_files(ods, OUT_ODS, SCHEMA_ODS,
                'ods_intl_crime_incident_di',
                '巴西犯罪地图原始表（RSS 直出，未做 LLM 校验）', False)
    write_files(dwd, OUT_DWD, SCHEMA_DWD,
                'dwd_intl_crime_incident_di',
                '巴西犯罪地图清洗表（RSS 抓取 + LLM 校验）', True)

    print(f'✅ 双层导出完成 (p_date={etl_dt})')
    print(f'   📦 ODS:  {OUT_ODS}/  ({len(ods)} 条)')
    for fn in ['incidents.json','incidents.csv','incidents.ndjson','manifest.json']:
        print(f'      - {fn:20} {os.path.getsize(OUT_ODS/fn):>10,} bytes')
    print(f'   📦 DWD:  {OUT_DWD}/  ({len(dwd)} 条)')
    for fn in ['incidents.json','incidents.csv','incidents.ndjson','manifest.json']:
        print(f'      - {fn:20} {os.path.getsize(OUT_DWD/fn):>10,} bytes')

if __name__=='__main__':
    main()
