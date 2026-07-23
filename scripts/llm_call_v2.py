#!/usr/bin/env python3
"""
LLM 三阶段调用脚本 v2（A=is_crime, B=type, C=geo）
============================================================
直接读 dwd 表 → 调 LLM → 回写 dwd 表（无中间文件）

用法：
  python3 scripts/llm_call_v2.py --stage a --provider mock
  python3 scripts/llm_call_v2.py --stage b --provider deepseek
  python3 scripts/llm_call_v2.py --stage c --provider deepseek --limit 100
"""
import os, sys, json, time, argparse, sqlite3, urllib.request
try:
    import requests
    _HAS_REQ = True
except ImportError:
    _HAS_REQ = False
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB   = ROOT / 'data' / 'crime_map.db'

# ============================================================
# Prompts
# ============================================================
PROMPT_A = """你是巴西新闻分析专家。判断一条新闻是否是“真实犯罪事件”。

✓ 犯罪：凶杀、抢劫、盗窃、强奸、贩毒、绑架、警方行动、派系 (CV/PCC)、诈骗、车辆犯罪、家暴、未成年涉案
✗ 非犯罪：政治 (Lula/Bolsonaro/选举/总统)、体育 (足球)、经济、娱乐 (明星/戏剧)、天气、病逝、意外事故、压力集会、公开设施项目、公共卫生

⚠️ 重要：请同时阅读标题和描述。描述中的上下文能揭示真相（如“morte”是病逝还是凶杀）。

只输出 JSON：{"id":"<id>","is_crime":true|false,"score":0-100,"reason":"<理由中文 30字>"}

ENTRADA:
id: {id}
title: {title}
description: {description}
source: {source}"""

PROMPT_B = """该新闻已确认是犯罪。请重新分类犯罪类型（13 选一）：
homicidio/roubo/furto/estupro/trafico/sequestro/violencia/policia/faccao/fraude/veiculo/menor/outros

规则：
- 出现"死亡" → homicidio（即使有派系，选主要犯罪）
- 以警方行动为主体 → policia
- PCC/CV 作为背景 → 主犯罪；作为主体 → faccao
- 抢劫带暴力 → roubo；无暴力 → furto

⚠️ 同时考虑标题和描述，描述能揭示真实事件主体。

只输出 JSON：{"id":"<id>","type":"<13选一>","score":0-100,"changed":true|false,"reason":"<中文 30字>"}

ENTRADA:
id: {id}
title: {title}
description: {description}
current_type: {current_type}"""

PROMPT_C = """该新闻已确认是犯罪。识别犯罪发生地点（州/市/街区）。

ESTADOS (2字母): AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO（BR=全国性）

规则：
- 描述里的明确城市 > 标题里的城市 > URL
- 著名街区：Rocinha/Maré/Copacabana/Tijuca → RJ；Liberdade/Mooca → SP；Boa Viagem/Madalena → PE
- city_method=default 说明原值只是兜底，高概率错
- 多个城市 → 选犯罪实际发生地

⚠️ 描述中常提及具体街区/被害人居住地，请优先使用。

只输出 JSON：{"id":"<id>","state":"<2字母>","city":"<城市>","neighborhood":"<街区或''>","score":0-100,"evidence":"<证据原文片段>","reason":"<中文>"}

ENTRADA:
id: {id}
title: {title}
description: {description}
link: {link}
current_state: {current_state}
current_city: {current_city}
city_method: {city_method}"""""

# ============================================================
# LLM Providers
# ============================================================
def call_llm(prompt_text, provider, api_key):
    """统一 LLM 调用"""
    if provider == 'mock':
        return mock_llm(prompt_text)

    # 🆕 万擎 Anthropic 协议（特殊处理）
    if provider == 'wanqing':
        url = os.environ.get('WQ_API_URL', 'https://wanqing-api.corp.kuaishou.com/api/gateway/v1/messages')
        model = os.environ.get('WQ_MODEL', 'ep-7zifa0-1777001276406194677')
        body = {
            'model': model,
            'max_tokens': 4096,  # 🔥 GLM 有 thinking 链，必须大
            'messages': [{'role': 'user', 'content': prompt_text + '\n\n请严格只输出一行 JSON，不要任何其他文字。'}]
        }
        # 🔒 用 requests（urllib timeout 在某些 socket 状态下不可靠）
        if _HAS_REQ:
            r = requests.post(url, json=body,
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                timeout=(10, 60))  # (connect=10s, read=60s)
            r.raise_for_status()
            resp = r.json()
        else:
            req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'),
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read())
        # Anthropic 协议：content 是 list，每项 {type:text|thinking, ...}
        text = ''
        thinking_text = ''
        for block in resp.get('content', []):
            if block.get('type') == 'text':
                text += block.get('text', '')
            elif block.get('type') == 'thinking':
                thinking_text += block.get('thinking', '')
        # 抽 JSON：优先 text，没有则从 thinking 末尾扒
        candidate = text if text.strip() else thinking_text
        import re as _re
        # 找最后一个完整 JSON 对象
        matches = _re.findall(r'\{[^{}]*\}', candidate)
        if matches:
            for m in reversed(matches):
                try:
                    return json.loads(m)
                except: continue
        # 兜底：贪婪匹配
        m = _re.search(r'\{.*\}', candidate, _re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise ValueError(f'no JSON in response (stop={resp.get("stop_reason")}, text_len={len(text)})')

    # OpenAI 兼容协议
    body = {'temperature':0,'response_format':{'type':'json_object'},
            'messages':[{'role':'user','content':prompt_text}]}
    if provider == 'deepseek':
        body['model'] = 'deepseek-chat'
        url = 'https://api.deepseek.com/v1/chat/completions'
        token = api_key
    elif provider == 'openai':
        body['model'] = 'gpt-4o-mini'
        url = 'https://api.openai.com/v1/chat/completions'
        token = api_key
    elif provider == 'kwai':
        body['model'] = os.environ.get('KWAI_LLM_MODEL','kwaiyii-13b')
        body.pop('response_format', None)
        url = os.environ['KWAI_LLM_URL']
        token = os.environ.get('KWAI_LLM_TOKEN','')
    else:
        raise ValueError(f'unknown provider {provider}')

    req = urllib.request.Request(url, data=json.dumps(body).encode(),
        headers={'Authorization':f'Bearer {token}','Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    content = resp['choices'][0]['message']['content']
    if '```' in content: content = content.split('```')[1].lstrip('json').strip()
    return json.loads(content)

def mock_llm(prompt_text):
    """Mock：从 prompt 里抓字段简单判断（同时看 title + description）"""
    import re
    m = re.search(r'id:\s*(\S+)', prompt_text)
    iid = m.group(1) if m else 'mock'
    m = re.search(r'title:\s*(.+)', prompt_text)
    title = (m.group(1) if m else '').lower()
    m = re.search(r'description:\s*(.+?)(?:\nlink:|\ncurrent_|\nsource:|$)', prompt_text, re.DOTALL)
    desc = (m.group(1) if m else '').lower()
    text = title + ' ' + desc   # 🆕 同时看标题和描述

    # Stage A
    if 'is_crime' in prompt_text:
        # 看法一：描述明确提及犯罪词→犯罪
        crime_kws = ['matou','assassin','baleado','tiros','assalto','roubo','furto','estupro','trafic','droga','preso','suspeito','homic','violênc','crim','sequestr','golpe','fraude','operacão policial']
        non_kws  = ['lula','bolsonaro','trump','presidente','eleição','copa','dólar','novela','xuxa','câncer','doença','funeral','luto']
        # 优先级：描述里有犯罪词 → 真；描述里有政治/病逝 → 假
        has_crime = any(k in text for k in crime_kws)
        has_non   = any(k in text for k in non_kws)
        is_crime = has_crime and not has_non
        if not has_crime and has_non: is_crime = False
        elif not has_crime and not has_non: is_crime = True   # 默认保留
        return {'id':iid,'is_crime':is_crime,'score':85 if has_crime else 60,
                'reason': '犯罪事件' if is_crime else ('政治娱乐' if has_non else '不明确')}
    # Stage B
    if 'classifique o tipo' in prompt_text.lower() or '重新分类犯罪类型' in prompt_text:
        if 'morte' in text or 'mort' in text or 'tiros' in text or 'matou' in text or 'assassin' in text:
            t = 'homicidio'
        elif 'tráfic' in text or 'droga' in text: t = 'trafico'
        elif 'roub' in text or 'assalt' in text:  t = 'roubo'
        elif 'pcc' in text or ' cv ' in text:     t = 'faccao'
        elif 'estupr' in text:                      t = 'estupro'
        else: t = 'outros'
        return {'id':iid,'type':t,'score':85,'changed':False,'reason':'关键词匹配'}
    # Stage C
    states = {'rio':'RJ','são paulo':'SP','sao paulo':'SP','manaus':'AM',
              'recife':'PE','belo horizonte':'MG','brasília':'DF','brasilia':'DF',
              'salvador':'BA','fortaleza':'CE','belém':'PA','belem':'PA','curitiba':'PR'}
    for k,v in states.items():
        if k in text: return {'id':iid,'state':v,'city':k.title(),'neighborhood':'','score':85,'evidence':k,'reason':'城市命中'}
    return {'id':iid,'state':'BR','city':'','neighborhood':'','score':40,'evidence':'','reason':'无明确地理'}

# ============================================================
# Stage 处理逻辑
# ============================================================
def get_pending_items(conn, stage, limit, state=None, city=None):
    """获取待处理记录"""
    cur = conn.cursor()
    sf = f" AND state='{state}'" if state else ""
    cf = f" AND city='{city}'" if city else ""
    if stage == 'a':
        sql = f"SELECT event_id,title,description,source_media FROM dwd_intl_crime_incident_di WHERE llm_a_is_crime IS NULL AND pub_ts >= strftime('%s','now','-7 days'){sf}{cf} ORDER BY pub_ts DESC"
    elif stage == 'b':
        sql = f"SELECT event_id,title,description,crime_type FROM dwd_intl_crime_incident_di WHERE llm_a_is_crime=1 AND llm_b_type IS NULL AND pub_ts >= strftime('%s','now','-7 days'){sf}{cf} ORDER BY pub_ts DESC"
    elif stage == 'c':
        sql = f"SELECT event_id,title,description,news_url,state,city,city_method FROM dwd_intl_crime_incident_di WHERE llm_a_is_crime=1 AND llm_c_state IS NULL AND pub_ts >= strftime('%s','now','-7 days'){sf}{cf} ORDER BY pub_ts DESC"
    if limit: sql += f' LIMIT {limit}'
    return cur.execute(sql).fetchall()

def build_prompt(stage, row):
    """根据 stage 拼 prompt"""
    if stage == 'a':
        # row: (event_id, title, description, source_media)
        return PROMPT_A.replace('{id}', row[0]).replace('{title}', row[1] or '') \
            .replace('{description}', (row[2] or '无摘要')[:400]).replace('{source}', row[3] or '')
    if stage == 'b':
        # row: (event_id, title, description, crime_type)
        return PROMPT_B.replace('{id}', row[0]).replace('{title}', row[1] or '') \
            .replace('{description}', (row[2] or '无摘要')[:400]).replace('{current_type}', row[3] or '')
    if stage == 'c':
        # row: (event_id, title, description, news_url, state, city, city_method)
        return PROMPT_C.replace('{id}', row[0]).replace('{title}', row[1] or '') \
            .replace('{description}', (row[2] or '无摘要')[:400]).replace('{link}', row[3] or '') \
            .replace('{current_state}', row[4] or '').replace('{current_city}', row[5] or '') \
            .replace('{city_method}', row[6] or '')

def save_result(conn, stage, r):
    """回写到 dwd 表"""
    cur = conn.cursor()
    eid = r.get('id')
    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    if stage == 'a':
        cur.execute("""UPDATE dwd_intl_crime_incident_di SET
            llm_a_is_crime=?, llm_a_score=?, llm_a_reason=?, llm_a_at=?
            WHERE event_id=?""",
            (1 if r.get('is_crime') else 0, r.get('score',0), (r.get('reason','') or '')[:200], now, eid))
    elif stage == 'b':
        cur.execute("""UPDATE dwd_intl_crime_incident_di SET
            llm_b_type=?, llm_b_score=?, llm_b_changed=?, llm_b_reason=?, llm_b_at=?
            WHERE event_id=?""",
            (r.get('type',''), r.get('score',0), 1 if r.get('changed') else 0,
             (r.get('reason','') or '')[:200], now, eid))
    elif stage == 'c':
        cur.execute("""UPDATE dwd_intl_crime_incident_di SET
            llm_c_state=?, llm_c_city=?, llm_c_neighbor=?, llm_c_score=?,
            llm_c_evidence=?, llm_c_reason=?, llm_c_at=?
            WHERE event_id=?""",
            (r.get('state',''), r.get('city',''), r.get('neighborhood',''),
             r.get('score',0), (r.get('evidence','') or '')[:200],
             (r.get('reason','') or '')[:200], now, eid))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', required=True, choices=['a','b','c'])
    ap.add_argument('--provider', default='mock', choices=['mock','deepseek','openai','kwai','wanqing'])
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--state', default=None, help='只跑指定州，如 SP/RJ')
    ap.add_argument('--city', default=None, help='只跑指定市，如 “São Paulo”')
    ap.add_argument('--throttle', type=float, default=0.0, help='每请求前 sleep 秒数，避免限流')
    args = ap.parse_args()

    # 检查 API Key
    if args.provider in ('deepseek','openai'):
        key_env = {'deepseek':'DEEPSEEK_API_KEY','openai':'OPENAI_API_KEY'}[args.provider]
        api_key = os.environ.get(key_env)
        if not api_key:
            print(f'❌ 请 export {key_env}=sk-...'); sys.exit(1)
    elif args.provider == 'wanqing':
        api_key = os.environ.get('WQ_API_KEY')
        if not api_key:
            print('❌ 请 export WQ_API_KEY=...'); sys.exit(1)
    elif args.provider == 'kwai':
        if not os.environ.get('KWAI_LLM_URL'):
            print('❌ 请 export KWAI_LLM_URL=...'); sys.exit(1)
        api_key = os.environ.get('KWAI_LLM_TOKEN','')
    else:
        api_key = None

    conn = sqlite3.connect(str(DB))
    items = get_pending_items(conn, args.stage, args.limit, state=args.state, city=args.city)
    print(f'🤖 Stage {args.stage.upper()} [{args.provider}] | 待处理 {len(items)} 条')
    if not items:
        print('✅ 没有待处理数据'); return

    t0 = time.time(); done = 0; failed = 0

    def work(row):
        prompt = build_prompt(args.stage, row)
        # 🆕 主动节流：每请求间隔（万擎对单 Key 并发严格）
        time.sleep(args.throttle)
        for attempt in range(8):
            try:
                return call_llm(prompt, args.provider, api_key)
            except Exception as e:
                msg = str(e)
                if '429' in msg or 'Too Many' in msg or 'rate' in msg.lower():
                    wait = min(2 ** attempt, 20)
                    time.sleep(wait)
                    continue
                if attempt < 2:
                    time.sleep(2)
                    continue
                return {'id': row[0], 'error': msg[:80]}
        return {'id': row[0], 'error': 'rate-limit after 8 retries'}

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(work, row) for row in items]
        for fut in as_completed(futs):
            r = fut.result()
            if 'error' in r:
                failed += 1
                if failed < 5: print(f'  ⚠️ {r["id"]}: {r["error"]}')
            else:
                save_result(conn, args.stage, r)
                done += 1
            if (done + failed) % 100 == 0:
                conn.commit()
                print(f'  ✓ {done+failed}/{len(items)} ({time.time()-t0:.0f}s)')

    conn.commit(); conn.close()
    print(f'\n✅ 完成: {done} 成功 / {failed} 失败 ({time.time()-t0:.1f}s)')

if __name__=='__main__':
    main()
