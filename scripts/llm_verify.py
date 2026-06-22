#!/usr/bin/env python3
"""
LLM 精准校验脚本
------------------------------------------------------------
对 public/rss_incidents.json 每条做 LLM 二次校验：
  1) 是否真的为犯罪事件（过滤政治/娱乐/广告）
  2) 真实发生州/市/街区
  3) 重新分类犯罪类型
  4) 给出置信度 0-100

支持 3 个 LLM Provider:
  - deepseek (api.deepseek.com)            # ⭐ 推荐：便宜 + 葡语强
  - openai   (api.openai.com gpt-4o-mini)  # 备选
  - kat      (公司内部，免费)               # 内部备选

用法:
  # Dry-run（不真的调 LLM，输出预期 prompt 给 5 条）
  python3 scripts/llm_verify.py --dry-run

  # 真正跑（需要 API KEY）
  export DEEPSEEK_API_KEY="sk-..."
  python3 scripts/llm_verify.py --provider deepseek --limit 50

  # 全量（约 2547 条，DeepSeek 大约 ¥1.3）
  python3 scripts/llm_verify.py --provider deepseek --limit 0

输出:
  public/rss_incidents.json 会被原地更新，新增字段:
    llm_verified  : bool   是否真的是犯罪事件
    llm_score     : int    置信度 0-100
    llm_state     : str    LLM 判定的州（2 字母代码）
    llm_city      : str    LLM 判定的城市
    llm_neighbor  : str    街区（如有）
    llm_type      : str    犯罪类型（重分类）
    llm_reason    : str    简短理由
    llm_at        : str    校验时间戳
"""
import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'public' / 'rss_incidents.json'

# 巴西标准化州列表（供 LLM 选择，避免乱写）
BR_STATES = ['AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO']
CRIME_TYPES = ['homicidio','roubo','furto','estupro','trafico','sequestro','violencia','policia','faccao','fraude','veiculo','menor','outros','NAO_CRIME']

PROMPT_SYSTEM = """Você é um analista que classifica notícias brasileiras sobre crimes.

Para cada manchete fornecida, responda APENAS em JSON com os campos:
{
  "is_crime": true | false,
  "score": 0-100,
  "state": "<sigla 2 letras dos 27 estados brasileiros, ex: SP, RJ, PE>",
  "city": "<nome da cidade>",
  "neighborhood": "<bairro se mencionado, senão ''>",
  "type": "homicidio|roubo|furto|estupro|trafico|sequestro|violencia|policia|faccao|fraude|veiculo|menor|outros|NAO_CRIME",
  "reason": "<frase curta em português>"
}

REGRAS:
- is_crime=false para notícias políticas, esportivas, econômicas, celebridades.
- score reflete sua confiança (90+ = alta certeza).
- state DEVE ser uma das 27 siglas. Se for nacional/desconhecido, use "BR".
- Se a manchete cita múltiplos estados, escolha onde o EVENTO ocorreu.
- "trafico" = tráfico de drogas.
- "faccao" = atividade do CV, PCC, ADA ou outra facção criminosa.
- "violencia" = briga, espancamento sem morte.
- Responda APENAS o JSON, sem markdown."""

def build_user_prompt(item):
    return f"Manchete: {item['title']}\nFonte: {item.get('source','')}\nLink: {item.get('link','')[:80]}"

# ---------------- LLM Providers ----------------
def call_deepseek(items, api_key, model='deepseek-chat'):
    """批量调用 DeepSeek。每次 1 条（DeepSeek 不支持批 prompt，但便宜）。"""
    results = []
    for it in items:
        body = {
            'model': model,
            'messages':[
                {'role':'system','content':PROMPT_SYSTEM},
                {'role':'user','content':build_user_prompt(it)},
            ],
            'temperature':0,
            'response_format':{'type':'json_object'},
        }
        req = urllib.request.Request(
            'https://api.deepseek.com/v1/chat/completions',
            data=json.dumps(body).encode(),
            headers={'Authorization':f'Bearer {api_key}','Content-Type':'application/json'},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read())
            content = resp['choices'][0]['message']['content']
            results.append(json.loads(content))
        except Exception as e:
            print(f'  ⚠️ {it["id"]}: {e}', file=sys.stderr)
            results.append(None)
    return results

def call_openai(items, api_key, model='gpt-4o-mini'):
    results = []
    for it in items:
        body = {
            'model': model,
            'messages':[
                {'role':'system','content':PROMPT_SYSTEM},
                {'role':'user','content':build_user_prompt(it)},
            ],
            'temperature':0,
            'response_format':{'type':'json_object'},
        }
        req = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=json.dumps(body).encode(),
            headers={'Authorization':f'Bearer {api_key}','Content-Type':'application/json'},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read())
            content = resp['choices'][0]['message']['content']
            results.append(json.loads(content))
        except Exception as e:
            print(f'  ⚠️ {it["id"]}: {e}', file=sys.stderr)
            results.append(None)
    return results

def call_kat(items, api_key=None):
    """公司内部 KAT-Coder（占位，根据实际网关地址填）"""
    print('⚠️  KAT provider 还需要你提供内部网关地址')
    return [None]*len(items)

PROVIDERS = {'deepseek':call_deepseek,'openai':call_openai,'kat':call_kat}

# ---------------- Main ----------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', choices=PROVIDERS.keys(), default='deepseek')
    parser.add_argument('--limit', type=int, default=20, help='处理多少条；0=全量')
    parser.add_argument('--dry-run', action='store_true', help='不调 LLM，只打印 prompt')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--only-default', action='store_true', help='只校验 city_method=default 的（最可能错）')
    parser.add_argument('--skip-verified', action='store_true', help='跳过已校验过的')
    args = parser.parse_args()

    with open(DATA) as f:
        items = json.load(f)
    print(f'📦 加载 {len(items)} 条')

    todo = items
    if args.only_default:
        todo = [x for x in todo if x.get('city_method')=='default']
        print(f'   过滤 city_method=default: {len(todo)} 条')
    if args.skip_verified:
        todo = [x for x in todo if 'llm_verified' not in x]
        print(f'   跳过已校验: {len(todo)} 条剩余')
    if args.limit > 0:
        todo = todo[:args.limit]
    print(f'🎯 本次处理 {len(todo)} 条')

    if args.dry_run:
        print('\n========== Dry Run (前 3 条 prompt) ==========')
        for it in todo[:3]:
            print(f'\n--- {it["id"]} ---')
            print('USER:', build_user_prompt(it))
        print('\n（dry-run 完成，未真正调用 LLM）')
        return

    api_key = os.environ.get({
        'deepseek':'DEEPSEEK_API_KEY',
        'openai':'OPENAI_API_KEY',
        'kat':'KAT_API_KEY',
    }[args.provider])
    if not api_key and args.provider!='kat':
        print(f'❌ 请设置环境变量 {args.provider.upper()}_API_KEY')
        return

    fn = PROVIDERS[args.provider]
    # 简单分批并发
    batch_size = max(1, len(todo)//args.workers)
    batches = [todo[i:i+batch_size] for i in range(0,len(todo),batch_size)]
    print(f'⚡ 启动 {len(batches)} 个并发 worker (batch={batch_size})')

    t0=time.time()
    all_results = [None]*len(todo)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(fn, b, api_key): (i*batch_size, b) for i,b in enumerate(batches)}
        for fut in as_completed(futures):
            offset, b = futures[fut]
            r = fut.result()
            for j, rr in enumerate(r):
                all_results[offset+j] = rr
            done=sum(1 for x in all_results if x is not None)
            print(f'  ✓ {done}/{len(todo)}')

    # 回写
    by_id = {it['id']:it for it in items}
    ok=0; fail=0; not_crime=0
    now_iso=time.strftime('%Y-%m-%dT%H:%M:%S')
    for it, r in zip(todo, all_results):
        if not r: fail+=1; continue
        if not r.get('is_crime'): not_crime+=1
        target = by_id[it['id']]
        target['llm_verified'] = r.get('is_crime',False)
        target['llm_score']    = r.get('score',0)
        target['llm_state']    = r.get('state','')
        target['llm_city']     = r.get('city','')
        target['llm_neighbor'] = r.get('neighborhood','')
        target['llm_type']     = r.get('type','')
        target['llm_reason']   = r.get('reason','')[:200]
        target['llm_at']       = now_iso
        target['llm_model']    = args.provider
        ok+=1

    with open(DATA,'w') as f:
        json.dump(items, f, ensure_ascii=False, indent=0)

    dt=time.time()-t0
    print(f'\n📊 完成 {ok} 条成功 / {fail} 条失败 / {not_crime} 条标记为非犯罪 (耗时 {dt:.1f}s)')
    print(f'✅ 已回写 {DATA}')

if __name__=='__main__':
    main()
