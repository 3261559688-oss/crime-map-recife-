#!/usr/bin/env python3
"""
gen_health.py - 生成 Ops Dashboard 所需的健康数据 JSON

产出（都写到 public/health/ 下）：
  - llm_stats.json    LLM 三阶段成功率/tokens/成本
  - analytics.json    Umami DAU/PV/事件/转化漏斗
  - feed.json         事件流（抓取/部署/告警）
  - infra.json        Vercel/GHA/Neon 配额

用法：
  python3 scripts/gen_health.py           # 全部生成
  python3 scripts/gen_health.py --llm     # 只更新 LLM
  python3 scripts/gen_health.py --umami   # 只更新 Umami

环境变量：
  UMAMI_URL, UMAMI_TOKEN, UMAMI_WEBSITE_ID
  VERCEL_TOKEN, VERCEL_PROJECT_ID
  GITHUB_TOKEN, GITHUB_REPO (格式: owner/repo)
"""
import os, sys, json, sqlite3, time, argparse, subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).parent.parent
DB = ROOT / 'data' / 'crime_map.db'
HEALTH_DIR = ROOT / 'public' / 'health'
HEALTH_DIR.mkdir(parents=True, exist_ok=True)

try:
    import requests
except ImportError:
    requests = None


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------- 1. LLM 统计 ----------
def gen_llm_stats():
    """从 SQLite dwd 表统计 LLM 三阶段成功率"""
    if not DB.exists():
        return {'error': f'DB not found: {DB}', 'generated_at': now_iso()}
    try:
        c = sqlite3.connect(str(DB)); cur = c.cursor()
        # 尝试从 dwd 表读（表名/字段可能不同，需按项目调整）
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        # 找 dwd 表
        dwd = next((t for t in tables if 'dwd' in t.lower() or 'incident' in t.lower()), None)
        stats = {'stages': [], 'cost_usd': 0, 'failures': {}, 'generated_at': now_iso()}
        if dwd:
            cols = [r[1] for r in cur.execute(f"PRAGMA table_info({dwd})")]
            total = cur.execute(f"SELECT COUNT(*) FROM {dwd}").fetchone()[0]
            # 假设有 is_crime / crime_type / city / lat 字段判断三阶段完成情况
            stats['stages'].append({'name':'RSS','in':0,'out':total})
            if 'is_crime' in cols:
                n1 = cur.execute(f"SELECT COUNT(*) FROM {dwd} WHERE is_crime IS NOT NULL").fetchone()[0]
                stats['stages'].append({'name':'LLM1_classify','in':total,'success':n1,'failed':total-n1,'rate':round(n1/total*100,1) if total else 0})
            if 'crime_type' in cols:
                n2 = cur.execute(f"SELECT COUNT(*) FROM {dwd} WHERE crime_type IS NOT NULL AND crime_type != ''").fetchone()[0]
                stats['stages'].append({'name':'LLM2_type','in':total,'success':n2,'failed':total-n2,'rate':round(n2/total*100,1) if total else 0})
            if 'lat' in cols or 'city' in cols:
                col = 'lat' if 'lat' in cols else 'city'
                n3 = cur.execute(f"SELECT COUNT(*) FROM {dwd} WHERE {col} IS NOT NULL").fetchone()[0]
                stats['stages'].append({'name':'LLM3_geo','in':total,'success':n3,'failed':total-n3,'rate':round(n3/total*100,1) if total else 0})
            stats['total_rows'] = total
        c.close()
        return stats
    except Exception as e:
        return {'error': str(e), 'generated_at': now_iso()}


# ---------- 2. Umami 分析 ----------
def gen_analytics():
    url = os.environ.get('UMAMI_URL')
    token = os.environ.get('UMAMI_TOKEN')
    wid = os.environ.get('UMAMI_WEBSITE_ID')
    if not (url and token and wid and requests):
        return {'error': 'UMAMI_URL/UMAMI_TOKEN/UMAMI_WEBSITE_ID 未配置', 'generated_at': now_iso(),
                'hint': '临时用 mock：DAU=0, PV=0'}
    try:
        H = {'Authorization': f'Bearer {token}'}
        end = int(time.time() * 1000)
        start = end - 86400 * 1000
        # 24h stats
        r = requests.get(f'{url}/api/websites/{wid}/stats', params={'startAt':start,'endAt':end}, headers=H, timeout=10)
        stats = r.json() if r.ok else {}
        # 30 天 DAU
        end30 = end; start30 = end - 30 * 86400 * 1000
        r2 = requests.get(f'{url}/api/websites/{wid}/pageviews', params={'startAt':start30,'endAt':end30,'unit':'day','timezone':'America/Sao_Paulo'}, headers=H, timeout=10)
        pv_daily = r2.json() if r2.ok else {}
        # 事件计数
        r3 = requests.get(f'{url}/api/websites/{wid}/events', params={'startAt':start,'endAt':end,'unit':'hour','timezone':'America/Sao_Paulo'}, headers=H, timeout=10)
        events = r3.json() if r3.ok else {}
        return {
            'pv_24h': stats.get('pageviews',0) if isinstance(stats.get('pageviews'),int) else stats.get('pageviews',{}).get('value',0),
            'uv_24h': stats.get('visitors',0) if isinstance(stats.get('visitors'),int) else stats.get('visitors',{}).get('value',0),
            'sessions_24h': stats.get('visits',0) if isinstance(stats.get('visits'),int) else stats.get('visits',{}).get('value',0),
            'bounces_24h': stats.get('bounces',0) if isinstance(stats.get('bounces'),int) else stats.get('bounces',{}).get('value',0),
            'totaltime_24h': stats.get('totaltime',0) if isinstance(stats.get('totaltime'),int) else stats.get('totaltime',{}).get('value',0),
            'daily_pv': pv_daily,
            'events_24h': events,
            'generated_at': now_iso()
        }
    except Exception as e:
        return {'error': str(e), 'generated_at': now_iso()}


# ---------- 2.5 Sessions（事件流回放）----------
def gen_sessions(max_sessions=100, hours=24):
    """拉 Umami sessions + 每个 session 的完整 activity 时间线"""
    url = os.environ.get('UMAMI_URL')
    token = os.environ.get('UMAMI_TOKEN')
    wid = os.environ.get('UMAMI_WEBSITE_ID')
    if not (url and token and wid and requests):
        return {'error': 'UMAMI env 未配置', 'generated_at': now_iso(), 'sessions': []}
    try:
        H = {'Authorization': f'Bearer {token}'}
        end = int(time.time() * 1000)
        start = end - hours * 3600 * 1000
        # 1. 拉 sessions 列表
        r = requests.get(f'{url}/api/websites/{wid}/sessions',
            params={'startAt':start,'endAt':end,'pageSize':max_sessions,'orderBy':'lastAt desc'},
            headers=H, timeout=15)
        sessions = r.json().get('data', []) if r.ok else []
        # 2. 每个 session 拉 activity
        enriched = []
        for s in sessions:
            sid = s['id']
            try:
                ra = requests.get(f'{url}/api/websites/{wid}/sessions/{sid}/activity',
                    params={'startAt':start,'endAt':end}, headers=H, timeout=10)
                activity = ra.json() if ra.ok else []
                # 按时间正序（Umami 返回是倒序）
                activity = sorted(activity, key=lambda x: x.get('createdAt',''))
                # 计算持续时长
                if activity:
                    t0 = activity[0]['createdAt']; t1 = activity[-1]['createdAt']
                    try:
                        dur = (datetime.fromisoformat(t1.replace('Z','+00:00')) -
                               datetime.fromisoformat(t0.replace('Z','+00:00'))).total_seconds()
                    except: dur = 0
                else:
                    dur = 0
                enriched.append({
                    'id': sid,
                    'device': s.get('device'),
                    'os': s.get('os'),
                    'browser': s.get('browser'),
                    'country': s.get('country'),
                    'region': s.get('region'),
                    'city': s.get('city'),
                    'language': s.get('language'),
                    'screen': s.get('screen'),
                    'first_at': s.get('firstAt'),
                    'last_at': s.get('lastAt'),
                    'views': s.get('views',0),
                    'events': s.get('events',0),
                    'visits': s.get('visits',0),
                    'duration_sec': int(dur),
                    'activity': activity
                })
            except Exception as e:
                enriched.append({'id':sid,'error':str(e)})
        return {'sessions': enriched, 'total': len(enriched), 'hours': hours, 'generated_at': now_iso()}
    except Exception as e:
        return {'error': str(e), 'generated_at': now_iso(), 'sessions': []}


# ---------- 3. 事件流 ----------
def gen_feed():
    """基于 meta.json / git log / GHA 状态自动生成告警事件"""
    feed = []
    meta_path = ROOT / 'public' / 'meta.json'
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        # 抓取健康
        rate = meta['feeds_success'] / meta['feeds_count'] if meta.get('feeds_count') else 0
        if rate < 0.5:
            feed.append({'sev':'critical','cat':'pipeline','icon':'🔴',
                'title':f'RSS 抓取成功率仅 {rate*100:.0f}%',
                'desc':f"{meta['feeds_success']}/{meta['feeds_count']} 源成功",
                'time':meta['generated_at'],
                'link':'https://github.com/dongyuhan03/crime-map-recife/actions'})
        elif rate < 0.7:
            feed.append({'sev':'warning','cat':'pipeline','icon':'🟡',
                'title':f'RSS 抓取成功率 {rate*100:.0f}%',
                'desc':f"{meta['feeds_success']}/{meta['feeds_count']} 源成功 · 有下降",
                'time':meta['generated_at'],'link':'#'})
        else:
            feed.append({'sev':'good','cat':'pipeline','icon':'🟢',
                'title':f'抓取正常 +{meta["total"]} 条累计',
                'desc':f"{meta['feeds_success']}/{meta['feeds_count']} 源健康",
                'time':meta['generated_at'],'link':'#'})
        # 新鲜度
        one_hour = meta.get('age_buckets',{}).get('< 1h',0)
        if one_hour == 0:
            feed.append({'sev':'warning','cat':'pipeline','icon':'⏰',
                'title':'过去 1h 无新新闻',
                'desc':'可能上游 feed 全静默或抓取挂了',
                'time':meta['generated_at'],'link':'#'})
    # git log 拿最近部署
    try:
        log = subprocess.check_output(['git','log','-5','--pretty=%h|%s|%ct'], cwd=ROOT, text=True).strip().split('\n')
        for line in log[:3]:
            sha,msg,ts = line.split('|',2)
            feed.append({'sev':'good','cat':'deploy','icon':'🚀',
                'title':f'部署 {sha}',
                'desc':msg[:60],
                'time':datetime.fromtimestamp(int(ts),tz=timezone.utc).isoformat(),
                'link':f'https://github.com/dongyuhan03/crime-map-recife/commit/{sha}'})
    except: pass
    return {'events': feed, 'generated_at': now_iso()}


# ---------- 4. 基础设施 ----------
def gen_infra():
    """Vercel + GHA + Neon 配额"""
    infra = {'quota': {}, 'generated_at': now_iso()}
    # Vercel
    vt = os.environ.get('VERCEL_TOKEN'); vp = os.environ.get('VERCEL_PROJECT_ID')
    if vt and requests:
        try:
            r = requests.get('https://api.vercel.com/v6/deployments', params={'projectId':vp,'limit':10},
                headers={'Authorization':f'Bearer {vt}'}, timeout=10)
            if r.ok:
                deps = r.json().get('deployments', [])
                infra['vercel_deployments'] = [{'sha':d.get('meta',{}).get('githubCommitSha','')[:7],'state':d.get('state'),'ts':d.get('createdAt')} for d in deps]
        except Exception as e:
            infra['vercel_error'] = str(e)
    # GHA
    gt = os.environ.get('GITHUB_TOKEN'); gr = os.environ.get('GITHUB_REPO','dongyuhan03/crime-map-recife')
    if gt and requests:
        try:
            r = requests.get(f'https://api.github.com/repos/{gr}/actions/runs', params={'per_page':10},
                headers={'Authorization':f'Bearer {gt}'}, timeout=10)
            if r.ok:
                runs = r.json().get('workflow_runs', [])
                infra['gha_runs'] = [{'id':r['id'],'status':r['status'],'conclusion':r['conclusion'],'name':r['name'],'ts':r['created_at']} for r in runs]
                # 本月配额
                r2 = requests.get(f'https://api.github.com/repos/{gr}/actions/runs/usage',
                    headers={'Authorization':f'Bearer {gt}'}, timeout=10)
        except Exception as e:
            infra['gha_error'] = str(e)
    return infra


# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--llm', action='store_true')
    ap.add_argument('--umami', action='store_true')
    ap.add_argument('--feed', action='store_true')
    ap.add_argument('--infra', action='store_true')
    ap.add_argument('--sessions', action='store_true')
    ap.add_argument('--session-hours', type=int, default=24)
    ap.add_argument('--session-limit', type=int, default=100)
    args = ap.parse_args()
    all_ = not (args.llm or args.umami or args.feed or args.infra or args.sessions)

    if all_ or args.llm:
        d = gen_llm_stats()
        (HEALTH_DIR / 'llm_stats.json').write_text(json.dumps(d, ensure_ascii=False, indent=2))
        print(f"✅ llm_stats.json  ({len(d.get('stages',[]))} stages)")
    if all_ or args.umami:
        d = gen_analytics()
        (HEALTH_DIR / 'analytics.json').write_text(json.dumps(d, ensure_ascii=False, indent=2))
        print(f"✅ analytics.json  ({'error: ' + d['error'] if 'error' in d else 'PV=' + str(d.get('pv_24h',0))})")
    if all_ or args.feed:
        d = gen_feed()
        (HEALTH_DIR / 'feed.json').write_text(json.dumps(d, ensure_ascii=False, indent=2))
        print(f"✅ feed.json       ({len(d['events'])} events)")
    if all_ or args.infra:
        d = gen_infra()
        (HEALTH_DIR / 'infra.json').write_text(json.dumps(d, ensure_ascii=False, indent=2))
        print(f"✅ infra.json      (Vercel: {'Y' if 'vercel_deployments' in d else 'N'} · GHA: {'Y' if 'gha_runs' in d else 'N'})")
    if all_ or args.sessions:
        d = gen_sessions(max_sessions=args.session_limit, hours=args.session_hours)
        (HEALTH_DIR / 'sessions.json').write_text(json.dumps(d, ensure_ascii=False, indent=2))
        cnt = len(d.get('sessions',[]))
        err = d.get('error','')
        print(f"✅ sessions.json   ({cnt} sessions{' · '+err if err else ''})")


if __name__ == '__main__':
    main()
