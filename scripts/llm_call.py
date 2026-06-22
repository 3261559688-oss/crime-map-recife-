#!/usr/bin/env python3
"""
真实 LLM 调用脚本（3 家可选）
============================================================
环境变量配置：
  DeepSeek:  export DEEPSEEK_API_KEY="sk-..."
  OpenAI:    export OPENAI_API_KEY="sk-..."
  快手内部:  export KWAI_LLM_URL="https://xxx.corp.kuaishou.com/v1/chat/completions"
            export KWAI_LLM_TOKEN="..."
            export KWAI_LLM_MODEL="kwaiyii-13b" (可选)

用法：
  python3 scripts/llm_call.py --provider deepseek
  python3 scripts/llm_call.py --provider openai --limit 100
  python3 scripts/llm_call.py --provider kwai --only-default
"""
import os, sys, json, time, argparse, sqlite3
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB   = ROOT / 'data' / 'crime_map.db'
OUT  = ROOT / 'data' / 'crime_llm_result.ndjson'

SYSTEM_PROMPT = """Você é analista de notícias brasileiras. Para cada manchete classifique:
{"id":"<原样>","llm_is_crime":true|false,"llm_score":0-100,"llm_state":"<SP/RJ/PE/BR>","llm_city":"<cidade>","llm_neighbor":"<bairro ou ''>","llm_type":"homicidio|roubo|furto|estupro|trafico|sequestro|violencia|policia|faccao|fraude|veiculo|menor|outros|NAO_CRIME","llm_reason":"<motivo curto em chinês>"}
Regras:
- Política/esporte/economia/entretenimento → NAO_CRIME
- Use sigla 2 letras dos 27 estados; nacional → BR
- Responda APENAS JSON, sem markdown, sem prefixo."""

def user_prompt(item):
    return f"id={item['event_id']}\ntitle={item['title']}\nsource={item.get('source_media','')}"

# ----------- Providers -----------
def call_deepseek(item, key):
    body = {'model':'deepseek-chat','messages':[
        {'role':'system','content':SYSTEM_PROMPT},
        {'role':'user','content':user_prompt(item)},
    ],'temperature':0,'response_format':{'type':'json_object'}}
    req = urllib.request.Request(
        'https://api.deepseek.com/v1/chat/completions',
        data=json.dumps(body).encode(),
        headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    return json.loads(resp['choices'][0]['message']['content'])

def call_openai(item, key):
    body = {'model':'gpt-4o-mini','messages':[
        {'role':'system','content':SYSTEM_PROMPT},
        {'role':'user','content':user_prompt(item)},
    ],'temperature':0,'response_format':{'type':'json_object'}}
    req = urllib.request.Request(
        'https://api.openai.com/v1/chat/completions',
        data=json.dumps(body).encode(),
        headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    return json.loads(resp['choices'][0]['message']['content'])

def call_kwai(item, _):
    """快手内部网关（兼容 OpenAI 格式即可）"""
    url   = os.environ.get('KWAI_LLM_URL')
    token = os.environ.get('KWAI_LLM_TOKEN','')
    model = os.environ.get('KWAI_LLM_MODEL','kwaiyii-13b')
    if not url:
        raise RuntimeError('请设置 KWAI_LLM_URL 环境变量')
    body = {'model':model,'messages':[
        {'role':'system','content':SYSTEM_PROMPT},
        {'role':'user','content':user_prompt(item)},
    ],'temperature':0}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
        headers={'Authorization':f'Bearer {token}','Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    content = resp['choices'][0]['message']['content']
    # 兼容：可能含 markdown 代码块
    if '```' in content:
        content = content.split('```')[1].lstrip('json').strip()
    return json.loads(content)

PROVIDERS = {'deepseek':call_deepseek,'openai':call_openai,'kwai':call_kwai}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--provider', required=True, choices=PROVIDERS)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--only-default', action='store_true')
    ap.add_argument('--skip-verified', action='store_true', default=True)
    ap.add_argument('--workers', type=int, default=4)
    args = ap.parse_args()

    key_env = {'deepseek':'DEEPSEEK_API_KEY','openai':'OPENAI_API_KEY','kwai':'KWAI_LLM_TOKEN'}[args.provider]
    api_key = os.environ.get(key_env, '')
    if args.provider != 'kwai' and not api_key:
        print(f'❌ 请设置环境变量 {key_env}'); sys.exit(1)

    conn = sqlite3.connect(str(DB)); conn.row_factory = sqlite3.Row
    sql = "SELECT event_id, title, source_media, city_method FROM dwd_intl_crime_incident_di WHERE 1=1"
    if args.only_default:    sql += " AND city_method='default'"
    if args.skip_verified:   sql += " AND llm_verified IS NULL"
    if args.limit:           sql += f" LIMIT {args.limit}"
    items = [dict(r) for r in conn.execute(sql)]
    print(f'📦 待处理 {len(items)} 条 ({args.provider})')
    if not items: return

    fn = PROVIDERS[args.provider]
    t0 = time.time(); results = []

    def work(it):
        try:
            r = fn(it, api_key)
            r['id'] = it['event_id']
            r['llm_model'] = args.provider
            return r
        except Exception as e:
            return {'id':it['event_id'],'error':str(e)[:80]}

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, it): it for it in items}
        done = 0
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r); done += 1
            if done % 50 == 0:
                print(f'  ✓ {done}/{len(items)} ({(time.time()-t0):.1f}s)')

    OUT.parent.mkdir(exist_ok=True)
    with open(OUT,'w') as f:
        for r in results:
            if 'error' not in r:
                f.write(json.dumps(r, ensure_ascii=False)+'\n')

    ok   = sum(1 for r in results if 'error' not in r)
    fail = sum(1 for r in results if 'error' in r)
    print(f'\n✅ 完成: {ok} 成功 / {fail} 失败 ({time.time()-t0:.1f}s)')
    print(f'   输出: {OUT}')
    print(f'\n🚀 下一步: python3 scripts/db.py merge {OUT}')

if __name__=='__main__':
    main()
