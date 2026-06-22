# 巴西犯罪地图 · 站内数据接入申请单（DR）

> **用途**：把 H5 项目的犯罪事件数据（每 30 分钟更新）落到站内 Hive 表，供数据 BP / 看板 / AB 实验使用。
>
> **填表人**：dongyuhan03
>
> **关联项目**：[crime-map-recife](https://github.com/3261559688-oss/crime-map-recife-)

---

## 一、基本信息

| 项 | 值 |
|---|---|
| 申请表名 | `dwd_intl_crime_incident_di`（建议命名，可由 BP 调整） |
| 业务部门 | 国际化业务-巴西-犯罪地图 |
| Owner | dongyuhan03 |
| 数据敏感级 | **L1 公开**（巴西公开新闻 RSS 抓取，无 PII） |
| 入仓集群 | `staging-sg`（新加坡海外集群，与 Trinity 埋点同集群） |
| 入仓频率 | 每 30 分钟刷新一次（建议接入平台用 1 小时/3 小时拉取节流） |
| 数据来源 | 巴西 50+ 葡语媒体 RSS（G1/Folha/UOL/Estadão/R7/Metrópoles 等） |
| 上线时间 | 2026-05-29（已运行 24 天，数据稳定） |

---

## 二、🔌 外部接口（4 个标准接口任选）

所有接口均为 **HTTPS GET 公网静态文件**，无鉴权，CDN 加速。

| 接口 | URL | 大小 | 推荐场景 |
|---|---|---|---|
| **JSON 数组** | https://crime-map-recife.vercel.app/api/incidents.json | ~1.8 MB | 简单接入，一次拉全量 |
| **CSV** | https://crime-map-recife.vercel.app/api/incidents.csv | ~1.0 MB | LOAD DATA 直传 Hive |
| **NDJSON** ⭐ | https://crime-map-recife.vercel.app/api/incidents.ndjson | ~1.8 MB | **推荐** — Spark/HDFS 标准 |
| **Manifest** | https://crime-map-recife.vercel.app/api/manifest.json | ~5 KB | 数据接入平台读 schema |

> ⭐ **推荐 NDJSON** —— 每行一个 JSON 对象，Spark `spark.read.json(path)` 直接可读，处理大数据时不需要全量加载。

### 接口示例（前 1 行）
```json
{
  "event_id": "inc_001",
  "title": "Liderança do CV no RJ tinha ligação com o PCC, aponta Exército",
  "crime_type": "faccao",
  "crime_type_zh": "派系",
  "city": "Brasília",
  "state": "DF",
  "lat": -15.780287,
  "lng": -47.904629,
  "source_media": "Metrópoles DF",
  "news_url": "https://www.metropoles.com/...",
  "pub_time": "2026-06-22T03:26:17+00:00",
  "pub_ts": 1782098777,
  "city_method": "default",
  "llm_verified": null,
  "llm_score": null,
  "llm_state": null,
  "llm_city": null,
  "llm_neighbor": null,
  "llm_type": null,
  "etl_dt": "20260622"
}
```

---

## 三、🏗 Hive 建表 SQL

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS dwd_intl_crime_incident_di (
  event_id      STRING   COMMENT '事件唯一 ID',
  title         STRING   COMMENT '新闻标题（葡语原文）',
  crime_type    STRING   COMMENT '犯罪类型枚举(13类)',
  crime_type_zh STRING   COMMENT '犯罪类型中文',
  city          STRING   COMMENT '城市',
  state         STRING   COMMENT '州（2 字母）',
  lat           DOUBLE   COMMENT '纬度',
  lng           DOUBLE   COMMENT '经度',
  source_media  STRING   COMMENT '来源媒体',
  news_url      STRING   COMMENT '原文链接',
  pub_time      STRING   COMMENT '发布时间 ISO',
  pub_ts        BIGINT   COMMENT '发布时间 unix 秒',
  city_method   STRING   COMMENT '地址解析方式 (default/title/url)',
  llm_verified  BOOLEAN  COMMENT 'LLM 校验是否真犯罪',
  llm_score     INT      COMMENT 'LLM 置信度 0-100',
  llm_state     STRING   COMMENT 'LLM 校正后的州',
  llm_city      STRING   COMMENT 'LLM 校正后的城市',
  llm_neighbor  STRING   COMMENT 'LLM 解析的街区',
  llm_type      STRING   COMMENT 'LLM 重分类的犯罪类型'
)
COMMENT '巴西犯罪地图明细表（RSS 抓取 + LLM 校验）'
PARTITIONED BY (p_date STRING COMMENT '分区日期 yyyyMMdd')
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
STORED AS TEXTFILE
LOCATION 'hdfs:///user/hive/warehouse/intl/crime_map/incident/';
```

---

## 四、📅 分区策略

- **分区键**：`p_date STRING (yyyyMMdd)`
- **分区粒度**：按天（每日一个分区）
- **数据生命周期**：保留 90 天
- **分区写入方式**：**幂等覆盖** — 每次拉取覆盖当天分区
  - 数据接入平台拉到的 `etl_dt` 字段就是当天分区值
  - 历史已发布事件可能因 RSS 翻页消失，所以**只覆盖当天分区即可，历史分区保留**

---

## 五、📊 关键查询示例（数据 BP 验证用）

```sql
-- ① 今日各州事件数
SELECT state, count(*) cnt
FROM dwd_intl_crime_incident_di
WHERE p_date = '20260622'
GROUP BY state
ORDER BY cnt DESC;

-- ② 各类犯罪分布
SELECT crime_type, crime_type_zh, count(*) cnt
FROM dwd_intl_crime_incident_di
WHERE p_date = '20260622'
GROUP BY crime_type, crime_type_zh;

-- ③ 与 Trinity 埋点 join 算北极星指标（新闻外跳率）
WITH page_uv AS (
  SELECT count(distinct did) uv FROM dwd_kwai_client_log_h5
  WHERE p_date='20260622' AND get_json_object(url_package,'$.page2')='CRIME_MAP_PAGE'
),
news_uv AS (
  SELECT count(distinct did) uv FROM dwd_kwai_client_log_h5
  WHERE p_date='20260622' AND event_type='CLICK_EVENT'
    AND get_json_object(element_package,'$.action2')='NEWS_OUTLINK'
)
SELECT news_uv.uv*100.0/page_uv.uv AS news_open_ctr_pct FROM page_uv, news_uv;

-- ④ 数据完整率监控（防止接口挂了未发现）
SELECT count(*) total, max(pub_time) latest_pub
FROM dwd_intl_crime_incident_di
WHERE p_date = '20260622';
-- 预期 total ≥ 2000，latest_pub ≤ 1 小时前
```

---

## 六、🚦 上线后监控建议

| 监控项 | 阈值 | 报警 |
|---|---|---|
| 当日数据条数 | < 1000 | 邮件通知 |
| 接口 HTTP 状态 | 非 200 | 立即报警 |
| 最新事件时间 | 距今 > 6 小时 | 报警（说明 RSS 抓取挂了） |
| `llm_verified` 完整率 | < 90% | 提醒补跑 LLM |

---

## 七、🤝 联系人

| 角色 | 联系人 |
|---|---|
| 业务方 | dongyuhan03 |
| 数据 BP | _待填_ |
| 数据接入平台 | _待填_（建议工单流程） |

---

## 八、📦 附件

- 完整代码仓库：https://github.com/3261559688-oss/crime-map-recife-
- Trinity 埋点 PRD：https://docs.corp.kuaishou.com/d/home/fcAD_BnWPztVc0rzFldfaykhU
- 主 PRD：https://docs.corp.kuaishou.com/d/home/fcABgCKDNEyrsn4HfXvL9M1Oi
- 字段定义脚本：[`scripts/export_for_warehouse.py`](https://github.com/3261559688-oss/crime-map-recife-/blob/main/scripts/export_for_warehouse.py)

---

*— DR 申请单 v1.0 —*
