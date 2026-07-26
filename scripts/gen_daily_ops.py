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
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
HEALTH = ROOT / 'public' / 'health'
HEALTH.mkdir(parents=True, exist_ok=True)

try:
    import requests
except Exception:
    requests = None

EVENT_LABELS = {
    'page_view': '进入页面',
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

    out = {
        'generated_at': now_iso(),
        'date_tz': 'America/Sao_Paulo',
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
            'event_card_show 是新版前端上线后的建议补充埋点。'
        ]
    }
    (HEALTH / 'daily_ops.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"✅ daily_ops.json generated: funnels={len(FUNNEL_CONFIG)} events24={sum(counts_24h.values())} events7d={sum(counts_7d.values())}")

if __name__ == '__main__':
    main()
