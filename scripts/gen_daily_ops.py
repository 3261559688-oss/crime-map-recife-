#!/usr/bin/env python3
"""
生成 ops.html 每日看板数据：数据新鲜度 + 配置化并行漏斗。
输出：public/health/daily_ops.json

原则：
- ops.html 只展示，核心指标由脚本生成。
- 漏斗配置驱动，后续前端新增埋点只需改配置。
- 拿不到的数据显式标记 missing，不造假。
"""
import json, os, time, math
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
HEALTH = ROOT / 'public' / 'health'
HEALTH.mkdir(parents=True, exist_ok=True)

try:
    import requests
except Exception:
    requests = None

EVENT_LABELS = {
    'page_view': '进入页面',
    'daily_active': '每日活跃用户',
    'geo_modal_show': '弹出定位弹窗',
    'geo_modal_allow': '点击允许定位',
    'geo_modal_deny': '点击拒绝定位',
    'geo_granted': '系统定位成功',
    'geo_denied': '系统定位失败/拒绝',
    'city_button_show': '城市按钮曝光',
    'city_modal_open': '打开城市弹窗',
    'city_search': '搜索城市',
    'city_switch': '成功切换城市',
    'city_modal_cancel': '取消城市弹窗',
    'type_filter_show': '类型筛选曝光',
    'type_filter': '切换类型筛选',
    'list_item_exposure': '列表内容曝光',
    'list_item_click': '点击列表新闻',
    'marker_click': '点击地图点位',
    'event_card_show': '事件卡片曝光',
    'news_open': '打开原文',
    'session_end': '会话结束',
}

FUNNEL_CONFIG = {
    'entry_geo': {
        'title': '进入与定位',
        'desc': '首次进入后的定位授权路径；geo 事件从 2026-07-27 修复后开始积累，历史不可回溯。',
        'steps': ['page_view', 'geo_modal_show', 'geo_modal_allow', 'geo_granted'],
        'side_steps': ['geo_modal_deny', 'geo_denied'],
    },
    'map_path': {
        'title': '地图路径',
        'desc': '用户直接点地图 marker 的消费路径；event_card_show 待新版前端上线后补入。',
        'steps': ['page_view', 'marker_click', 'news_open'],
        'future_steps': ['event_card_show'],
    },
    'list_path': {
        'title': '列表路径',
        'desc': '用户上滑/看到列表后点击新闻的消费路径。',
        'steps': ['page_view', 'list_item_exposure', 'list_item_click', 'news_open'],
    },
    'city_path': {
        'title': '城市切换',
        'desc': '城市选择弹窗的发现、搜索和切换路径。',
        'steps': ['city_button_show', 'city_modal_open', 'city_search', 'city_switch'],
        'side_steps': ['city_modal_cancel'],
    },
    'filter_path': {
        'title': '类型筛选',
        'desc': '顶部犯罪类型筛选曝光到主动切换。',
        'steps': ['type_filter_show', 'type_filter'],
    },
}

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:
        return default

def percentile(values, p):
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p
    f = math.floor(k); c = math.ceil(k)
    if f == c:
        return xs[int(k)]
    return xs[f] * (c-k) + xs[c] * (k-f)

def event_counts_from_items(items):
    counts = {}
    for e in items or []:
        name = e.get('eventName') or ('pageview' if e.get('eventType') == 1 else None)
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    return counts

def event_props(e):
    """兼容 Umami 不同版本的 event data 字段。"""
    props = e.get('eventData') or e.get('data') or e.get('properties') or e.get('payload') or {}
    if isinstance(props, str):
        try:
            props = json.loads(props)
        except Exception:
            props = {}
    return props if isinstance(props, dict) else {}

def event_name(e):
    return e.get('eventName') or ('pageview' if e.get('eventType') == 1 else None)

def event_user_id(e):
    props = event_props(e)
    return (
        props.get('uid') or props.get('cm_uid') or props.get('user_id') or
        e.get('visitorId') or e.get('visitor_id') or e.get('sessionId') or e.get('session_id')
    )

def build_d1_retention_from_events(day_events):
    """基于 daily_active 优先、page_view 兜底的真实 D1 留存。
    口径：D0 活跃用户中，D1 也活跃的用户数 / D0 活跃用户数。
    """
    users_by_date = {}
    source_counts = {}
    for day in day_events:
        date = day.get('date')
        users = set()
        source = 'daily_active'
        for e in day.get('items') or []:
            if event_name(e) != 'daily_active':
                continue
            uid = event_user_id(e)
            if uid:
                users.add(str(uid))
        if not users:
            source = 'page_view_fallback'
            for e in day.get('items') or []:
                if event_name(e) != 'page_view':
                    continue
                uid = event_user_id(e)
                if uid:
                    users.add(str(uid))
        users_by_date[date] = users
        source_counts[date] = source

    items = []
    dates = [d.get('date') for d in day_events]
    for i, date in enumerate(dates[:-1]):
        next_date = dates[i+1]
        cohort = users_by_date.get(date, set())
        returned = cohort & users_by_date.get(next_date, set())
        items.append({
            'cohort_date': date,
            'return_date': next_date,
            'cohort_users': len(cohort),
            'returned_next_day': len(returned),
            'd1_rate': round(len(returned) / len(cohort) * 100, 1) if cohort else None,
            'source': source_counts.get(date, 'missing'),
        })
    latest = items[-1] if items else None
    return {
        'timezone': 'America/Sao_Paulo',
        'definition': 'D0 活跃用户中，D1 也活跃的用户数 / D0 活跃用户数；优先 daily_active，缺失时 page_view 兜底。',
        'latest': latest,
        'items': items,
        'data_status': 'ok' if latest and latest.get('cohort_users', 0) > 0 else 'insufficient_data',
    }

def fetch_umami_events(hours):
    url = os.environ.get('UMAMI_URL')
    token = os.environ.get('UMAMI_TOKEN')
    wid = os.environ.get('UMAMI_WEBSITE_ID')
    if not (url and token and wid and requests):
        return None, 'UMAMI env or requests missing'
    end = int(time.time() * 1000)
    start = end - hours * 3600 * 1000
    try:
        r = requests.get(
            f'{url}/api/websites/{wid}/events',
            params={'startAt': start, 'endAt': end, 'unit': 'hour', 'timezone': 'America/Sao_Paulo', 'pageSize': 10000},
            headers={'Authorization': f'Bearer {token}'}, timeout=20)
        if not r.ok:
            return None, f'HTTP {r.status_code}: {r.text[:120]}'
        j = r.json()
        return event_counts_from_items(j.get('data') if isinstance(j, dict) else j), None
    except Exception as e:
        return None, str(e)


def fetch_umami_events_range(start_ms, end_ms, include_items=False):
    url = os.environ.get('UMAMI_URL')
    token = os.environ.get('UMAMI_TOKEN')
    wid = os.environ.get('UMAMI_WEBSITE_ID')
    if not (url and token and wid and requests):
        return (None, None, 'UMAMI env or requests missing') if include_items else (None, 'UMAMI env or requests missing')
    try:
        r = requests.get(
            f'{url}/api/websites/{wid}/events',
            params={'startAt': start_ms, 'endAt': end_ms, 'unit': 'hour', 'timezone': 'America/Sao_Paulo', 'pageSize': 10000},
            headers={'Authorization': f'Bearer {token}'}, timeout=20)
        if not r.ok:
            err = f'HTTP {r.status_code}: {r.text[:120]}'
            return (None, None, err) if include_items else (None, err)
        j = r.json()
        items = j.get('data') if isinstance(j, dict) else j
        counts = event_counts_from_items(items)
        return (counts, items or [], None) if include_items else (counts, None)
    except Exception as e:
        return (None, None, str(e)) if include_items else (None, str(e))

def build_daily_history(days=14):
    """按 America/Sao_Paulo 自然日生成最近 N 天漏斗快照和 D1 留存原始 cohort。"""
    tz = ZoneInfo('America/Sao_Paulo')
    today = datetime.now(tz).date()
    history = []
    errors = {}
    day_events = []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        start = datetime(day.year, day.month, day.day, tzinfo=tz)
        end = start + timedelta(days=1)
        counts, items, err = fetch_umami_events_range(int(start.timestamp()*1000), int(end.timestamp()*1000), include_items=True)
        if counts is None:
            counts = {}
            items = []
            errors[str(day)] = err
        day_events.append({'date': str(day), 'items': items})
        history.append({
            'date': str(day),
            'start_at': start.isoformat(),
            'end_at': end.isoformat(),
            'event_counts': counts,
            'funnels': build_funnel(FUNNEL_CONFIG, counts),
            'summary': {
                'page_view': counts.get('page_view', 0),
                'geo_modal_show': counts.get('geo_modal_show', 0),
                'marker_click': counts.get('marker_click', 0),
                'list_item_exposure': counts.get('list_item_exposure', 0),
                'list_item_click': counts.get('list_item_click', 0),
                'news_open': counts.get('news_open', 0),
            }
        })
    return {'days': days, 'timezone': 'America/Sao_Paulo', 'items': history, 'errors': errors, 'retention': build_d1_retention_from_events(day_events)}

def build_funnel(config, counts):
    funnels = {}
    for key, cfg in config.items():
        steps = []
        prev = None
        first = None
        for ev in cfg['steps']:
            val = int(counts.get(ev, 0) or 0)
            if first is None:
                first = val
            steps.append({
                'event': ev,
                'label': EVENT_LABELS.get(ev, ev),
                'count': val,
                'from_prev_rate': round(val / prev * 100, 1) if prev else None,
                'from_start_rate': round(val / first * 100, 1) if first else None,
                'data_status': 'ok' if val > 0 else 'zero_or_missing'
            })
            prev = val
        side = []
        for ev in cfg.get('side_steps', []):
            side.append({'event': ev, 'label': EVENT_LABELS.get(ev, ev), 'count': int(counts.get(ev, 0) or 0)})
        funnels[key] = {
            'title': cfg['title'], 'desc': cfg.get('desc',''), 'steps': steps, 'side_steps': side,
            'future_steps': [{'event': ev, 'label': EVENT_LABELS.get(ev, ev)} for ev in cfg.get('future_steps', [])]
        }
    return funnels



def count_by(items, key, top=10):
    d = {}
    for x in items or []:
        v = x.get(key) or 'Unknown'
        d[v] = d.get(v, 0) + 1
    return sorted([{'name': k, 'count': v} for k, v in d.items()], key=lambda x: x['count'], reverse=True)[:top]

def age_buckets(items, now_ts=None):
    now_ts = now_ts or int(time.time())
    buckets = {'<1h': 0, '1-6h': 0, '6-24h': 0, '1-3d': 0, '3-7d': 0}
    for x in items or []:
        ts = x.get('pub_ts')
        if not ts:
            continue
        h = (now_ts - int(ts)) / 3600
        if h < 1: buckets['<1h'] += 1
        elif h < 6: buckets['1-6h'] += 1
        elif h < 24: buckets['6-24h'] += 1
        elif h < 72: buckets['1-3d'] += 1
        else: buckets['3-7d'] += 1
    return buckets

def stage_map(llm):
    return {s.get('name'): s for s in (llm or {}).get('stages', [])}

def build_unified_sections(rss, meta, analytics, llm, infra, counts_24h, counts_7d, durations):
    latest = max([x.get('pub_date','') for x in rss if x.get('pub_date')] or [meta.get('latest')])
    verified = meta.get('llm_verified_count', sum(1 for x in rss if x.get('llm_verified') is True))
    count = len(rss)
    verified_rate = round(verified / count * 100, 1) if count else 0
    pv = analytics.get('pv_24h')
    uv = analytics.get('uv_24h')
    sessions = analytics.get('sessions_24h')
    bounces = analytics.get('bounces_24h')
    bounce_rate = round(bounces / sessions * 100, 1) if sessions else None
    news_open = counts_24h.get('news_open', 0)
    page_view = counts_24h.get('page_view', 0)
    marker_click = counts_24h.get('marker_click', 0)
    list_exp = counts_24h.get('list_item_exposure', 0)
    list_click = counts_24h.get('list_item_click', 0)
    error_count = counts_24h.get('error', 0)
    sm = stage_map(llm)
    a = sm.get('LLM_A') or sm.get('A') or {}
    b = sm.get('LLM_B') or sm.get('B') or {}
    c = sm.get('LLM_C') or sm.get('C') or {}
    gha_runs = (infra or {}).get('gha_runs', [])
    latest_run = gha_runs[0] if gha_runs else {}
    success_5 = sum(1 for r in gha_runs[:5] if r.get('conclusion') == 'success')
    file_sizes = {}
    for rel in ['public/rss_incidents.json','public/rss_incidents_lite.json','public/meta.json','public/health/daily_ops.json','data/crime_map.db']:
        path = ROOT / rel
        if path.exists(): file_sizes[rel] = path.stat().st_size
    interaction = {
        'marker_click_rate': round(marker_click / page_view * 100, 1) if page_view else None,
        'list_exposure_rate': round(list_exp / page_view * 100, 1) if page_view else None,
        'list_click_rate': round(list_click / list_exp * 100, 1) if list_exp else None,
        'news_open_rate': round(news_open / page_view * 100, 2) if page_view else None,
    }
    overview = {
        'generated_at': now_iso(),
        'health': {
            'data_freshness': 'ok' if latest else 'warn',
            'frontend': 'ok' if count > 0 else 'err',
            'analytics': 'ok' if pv is not None else 'warn',
            'llm': 'warn' if (meta.get('mode') == 'raw_7d_unverified_until_llm_ready') else 'ok',
            'infra': 'ok' if latest_run.get('conclusion') == 'success' else 'warn',
        },
        'kpis': {
            'frontend_count': count, 'latest_pub_date': latest, 'mode': meta.get('mode'),
            'llm_verified_count': verified, 'llm_verified_rate': verified_rate,
            'uv_24h': uv, 'pv_24h': pv, 'sessions_24h': sessions, 'bounce_rate_24h': bounce_rate,
            'news_open_24h': news_open, 'news_open_rate_24h': interaction['news_open_rate'],
        }
    }
    pipeline = {
        'raw_7d_count': count,
        'latest_pub_date': latest,
        'mode': meta.get('mode'),
        'llm_verified_count': verified,
        'llm_verified_rate': verified_rate,
        'top_cities': count_by(rss, 'city', 10),
        'top_types': count_by(rss, 'type', 10),
        'age_buckets': age_buckets(rss),
        'llm_stages': {'a': a, 'b': b, 'c': c, 'total_rows': llm.get('total_rows')},
    }
    frontend = {
        'status': 'ok' if count > 0 else 'err',
        'data_source': {'count': count, 'lite_count': min(200, count), 'latest_pub_date': latest, 'mode': meta.get('mode'), 'llm_verified_count': verified, 'llm_verified_rate': verified_rate},
        'interaction': interaction,
        'errors': {'count_24h': error_count, 'error_rate_per_page_view': round(error_count / page_view * 100, 2) if page_view else None},
        'performance': {'duration_percentiles_source': 'sessions activity sample', 'load_ms_p50': None, 'load_ms_p80': None, 'load_ms_p90': None, 'todo': '接入 page_view.load_ms event_data 后填充'},
        'files': file_sizes,
    }
    business = {
        'uv_24h': uv, 'pv_24h': pv, 'sessions_24h': sessions, 'bounce_rate_24h': bounce_rate,
        'engagement': interaction,
        'content_touch_rate': interaction['list_exposure_rate'],
        'news_open_count_24h': news_open,
        'news_open_rate_24h': interaction['news_open_rate'],
        'city_switch_24h': counts_24h.get('city_switch', 0),
        'type_filter_24h': counts_24h.get('type_filter', 0),
    }
    infra_section = {
        'gha': {'latest': latest_run, 'success_5': success_5, 'total_checked': len(gha_runs[:5])},
        'vercel': {'deployments': (infra or {}).get('vercel_deployments', [])[:5]},
        'data_files': file_sizes,
        'umami_api': 'ok' if pv is not None else 'warn',
        'db_size_bytes': file_sizes.get('data/crime_map.db'),
    }
    architecture = {
        'current_mode': meta.get('mode'),
        'current_mode_label': '临时 raw 7d 前端口径' if meta.get('mode') == 'raw_7d_unverified_until_llm_ready' else '严格 LLM published 口径',
        'known_risks': [
            'GHA 公网 runner 无法访问内网万擎，LLM 自动化待 self-hosted runner',
            'raw 7d 是临时产品可用性口径，准确性低于 llm_a_is_crime=1 正式口径',
            'geo 定位系统成功率当前为 0，需要拆 geo_denied.code 并优化定位策略',
        ],
        'next_steps': ['Mac self-hosted runner 承接 LLM job', '补 geo_denied.code 维度', 'event_card_show 随新版前端上线补埋点'],
    }
    return overview, pipeline, frontend, business, infra_section, architecture

def main():
    analytics = load_json(HEALTH / 'analytics.json', {}) or {}
    meta = load_json(ROOT / 'public' / 'meta.json', {}) or {}
    sessions = load_json(HEALTH / 'sessions.json', {}) or {}
    rss = load_json(ROOT / 'public' / 'rss_incidents.json', []) or []

    counts_24h, err24 = fetch_umami_events(24)
    counts_7d, err7 = fetch_umami_events(24*7)
    if counts_24h is None:
        counts_24h = event_counts_from_items((analytics.get('events_24h') or {}).get('data', []))
    if counts_7d is None:
        # 没有 7d API 时，先复用 24h 并标记 partial，避免空白
        counts_7d = dict(counts_24h)

    durations = [s.get('duration_sec') for s in sessions.get('sessions', []) if isinstance(s.get('duration_sec'), (int, float)) and s.get('duration_sec') >= 0]
    duration_percentiles = {
        'source': 'health/sessions.json activity duration_sec (recent sample)',
        'sample_size': len(durations),
        'p50_sec': round(percentile(durations, .50), 1) if durations else None,
        'p80_sec': round(percentile(durations, .80), 1) if durations else None,
        'p90_sec': round(percentile(durations, .90), 1) if durations else None,
        'p95_sec': round(percentile(durations, .95), 1) if durations else None,
        'note': '后续可切到 session_end.duration_ms / active_ms 原始 event_data 分位数。'
    }

    latest = None
    if rss:
        latest = max([x.get('pub_date','') for x in rss if x.get('pub_date')] or [None])

    llm = load_json(HEALTH / 'llm_stats.json', {}) or {}
    infra = load_json(HEALTH / 'infra.json', {}) or {}
    overview, pipeline, frontend, business, infra_section, architecture = build_unified_sections(
        rss, meta, analytics, llm, infra, counts_24h, counts_7d, durations
    )

    daily_history = build_daily_history(days=int(os.environ.get('DAILY_OPS_HISTORY_DAYS', '14')))

    out = {
        'generated_at': now_iso(),
        'date_tz': 'America/Sao_Paulo',
        'daily_history': daily_history,
        'retention': daily_history.get('retention', {}),
        'overview': overview,
        'pipeline': pipeline,
        'frontend': frontend,
        'analytics': {
            'summary': overview['kpis'],
            'duration_percentiles': duration_percentiles,
            'event_counts_24h': counts_24h,
            'event_counts_7d': counts_7d,
            'retention': daily_history.get('retention', {}),
        },
        'business': business,
        'infra': infra_section,
        'architecture': architecture,
        # Backward-compatible fields used by current ops.html renderDailyFunnel
        'data_status': {
            'frontend_count': len(rss),
            'latest_pub_date': latest or meta.get('latest'),
            'mode': meta.get('mode'),
            'llm_verified_count': meta.get('llm_verified_count', sum(1 for x in rss if x.get('llm_verified') is True)),
        },
        'analytics_summary': {
            'pv_24h': analytics.get('pv_24h'),
            'uv_24h': analytics.get('uv_24h'),
            'sessions_24h': analytics.get('sessions_24h'),
            'bounces_24h': analytics.get('bounces_24h'),
            'bounce_rate_24h': round((analytics.get('bounces_24h',0) / analytics.get('sessions_24h',1))*100, 1) if analytics.get('sessions_24h') else None,
            'totaltime_24h': analytics.get('totaltime_24h'),
        },
        'duration_percentiles': duration_percentiles,
        'event_counts': {
            'last_24h': counts_24h,
            'last_7d': counts_7d,
            'errors': {'24h': err24, '7d': err7},
        },
        'funnels': {
            'last_24h': build_funnel(FUNNEL_CONFIG, counts_24h),
            'last_7d': build_funnel(FUNNEL_CONFIG, counts_7d),
            'config': FUNNEL_CONFIG,
        },
        'notes': [
            '地图路径和列表路径是并行路径，不串成单链漏斗。',
            'geo_modal_show 已接入，但历史不可回溯；从修复后新用户开始计数。',
            'D1 留存优先使用 daily_active 事件；该事件上线前的日期使用 page_view 用户标识兜底，拿不到用户标识时显示样本不足。',
            'event_card_show 是新版前端上线后的建议补充埋点。'
        ]
    }
    (HEALTH / 'daily_ops.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"✅ daily_ops.json generated: funnels={len(FUNNEL_CONFIG)} events24={sum(counts_24h.values())} events7d={sum(counts_7d.values())}")

if __name__ == '__main__':
    main()
