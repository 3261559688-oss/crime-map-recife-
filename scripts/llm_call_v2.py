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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB   = ROOT / 'data' / 'crime_map.db'

# ============================================================
# Prompts
# ============================================================
PROMPT_A = """Você é analista de notícias brasileiras. Identifique se uma manchete é sobre CRIME REAL.

✓ CRIME: homicídio, roubo, furto, estupro, tráfico, sequestro, violência, operação policial, facção (CV/PCC), fraude, veículo, menor
✗ NÃO CRIME: política, esportes, economia, entretenimento, clima

Responda APENAS JSON: {"id":"<id>","is_crime":true|false,"score":0-100,"reason":"<理由中文 30字>"}

ENTRADA:
id: {id}
title: {title}
source: {source}"""

PROMPT_B = """A notícia foi confirmada CRIME. Classifique o tipo (13 opções):
homicidio/roubo/furto/estupro/trafico/sequestro/violencia/policia/faccao/fraude/veiculo/menor/outros

REGRAS:
- Morte → homicidio (mesmo com facção, escolha o crime principal)
- Operação policial principal → policia
- PCC/CV como contexto → crime principal; como ação → faccao
- Roubo com violência → roubo; sem → furto

Responda APENAS JSON: {"id":"<id>","type":"<13选1>","score":0-100,"changed":true|false,"reason":"<中文 30字>"}

ENTRADA:
id: {id}
title: {title}
current_type: {current_type}"""

PROMPT_C = """A notícia foi confirmada CRIME. Identifique ONDE aconteceu.

ESTADOS: AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO (BR=nacional)

REGRAS:
- Cidade explícita na manchete tem prioridade
- Bairros famosos: Rocinha/Maré/Copacabana/Tijuca → RJ; Liberdade/Mooca → SP; Boa Viagem/Madalena → PE
- city_method=default = original é palpite, alta chance de erro
- Múltiplas cidades → onde o crime aconteceu

Responda APENAS JSON: {"id":"<id>","state":"<2letras>","city":"<cidade>","neighborhood":"<bairro ou ''>","score":0-100,"evidence":"<frase>","reason":"<中文>"}

ENTRADA:
id: {id}
title: {title}
link: {link}
current_state: {current_state}
current_city: {current_city}
city_method: {city_method}"""

# ============================================================
# LLM Providers
# ============================================================
def call_llm(prompt_text, provider, api_key):
    """统一 LLM 调用"""
    if provider == 'mock':
        return mock_llm(prompt_text)
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
    """Mock：从 prompt 里抓字段简单判断"""
    import re
    # 取 id
    m = re.search(r'id:\s*(\S+)', prompt_text)
    iid = m.group(1) if m else 'mock'
    # 取 title
    m = re.search(r'title:\s*(.+)', prompt_text)
    title = (m.group(1) if m else '').lower()

    # Stage A
    if 'is_crime' in prompt_text:
        non = any(k in title for k in ['lula','bolsonaro','trump','presidente','eleição','copa','dólar','novela'])
        return {'id':iid,'is_crime':not non,'score':92,
                'reason':'政治娱乐' if non else '犯罪事件'}
    # Stage B
    if 'classifique o tipo' in prompt_text.lower() or 'classifique o tipo' in prompt_text:
        if 'morte' in title or 'mort' in title or 'tiros' in title:
            t = 'homicidio'
        elif 'tráfic' in title or 'droga' in title: t = 'trafico'
        elif 'roub' in title or 'assalt' in title:  t = 'roubo'
        elif 'pcc' in title or ' cv ' in title:     t = 'faccao'
        elif 'estupr' in title:                      t = 'estupro'
        else: t = 'outros'
        return {'id':iid,'type':t,'score':85,'changed':False,'reason':'关键词匹配'}
    # Stage C
    states = {'rio':'RJ','são paulo':'SP','sao paulo':'SP','manaus':'AM',
              'recife':'PE','belo horizonte':'MG','brasília':'DF','brasilia':'DF',
              'salvador':'BA','fortaleza':'CE','belém':'PA','belem':'PA','curitiba':'PR'}
    for k,v in states.items():
        if k in title: return {'id':iid,'state':v,'city':k.title(),'neighborhood':'','score':85,'evidence':k,'reason':'城市命中'}
    return {'id':iid,'state':'BR','city':'','neighborhood':'','score':40,'evidence':'','reason':'无明确地理'}

# ============================================================
# Stage 处理逻辑
# ============================================================
def get_pending_items(conn, stage, limit):
    """获取待处理记录"""
    cur = conn.cursor()
    if stage == 'a':
        sql = "SELECT event_id,title,source_media FROM dwd_intl_crime_incident_di WHERE llm_a_is_crime IS NULL"
    elif stage == 'b':
        sql = "SELECT event_id,title,crime_type FROM dwd_intl_crime_incident_di WHERE llm_a_is_crime=1 AND llm_b_type IS NULL"
    elif stage == 'c':
        sql = "SELECT event_id,title,news_url,state,city,city_method FROM dwd_intl_crime_incident_di WHERE llm_a_is_crime=1 AND llm_c_state IS NULL"
    if limit: sql += f' LIMIT {limit}'
    return cur.execute(sql).fetchall()

def build_prompt(stage, row):
    """根据 stage 拼 prompt"""
    if stage == 'a':
        return PROMPT_A.replace('{id}', row[0]).replace('{title}', row[1] or '').replace('{source}', row[2] or '')
    if stage == 'b':
        return PROMPT_B.replace('{id}', row[0]).replace('{title}', row[1] or '').replace('{current_type}', row[2] or '')
    if stage == 'c':
        return PROMPT_C.replace('{id}', row[0]).replace('{title}', row[1] or '') \
            .replace('{link}', row[2] or '').replace('{current_state}', row[3] or '') \
            .replace('{current_city}', row[4] or '').replace('{city_method}', row[5] or '')

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
    ap.add_argument('--provider', default='mock', choices=['mock','deepseek','openai','kwai'])
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--workers', type=int, default=4)
    args = ap.parse_args()

    # 检查 API Key
    if args.provider in ('deepseek','openai'):
        key_env = {'deepseek':'DEEPSEEK_API_KEY','openai':'OPENAI_API_KEY'}[args.provider]
        api_key = os.environ.get(key_env)
        if not api_key:
            print(f'❌ 请 export {key_env}=sk-...'); sys.exit(1)
    elif args.provider == 'kwai':
        if not os.environ.get('KWAI_LLM_URL'):
            print('❌ 请 export KWAI_LLM_URL=...'); sys.exit(1)
        api_key = os.environ.get('KWAI_LLM_TOKEN','')
    else:
        api_key = None

    conn = sqlite3.connect(str(DB))
    items = get_pending_items(conn, args.stage, args.limit)
    print(f'🤖 Stage {args.stage.upper()} [{args.provider}] | 待处理 {len(items)} 条')
    if not items:
        print('✅ 没有待处理数据'); return

    t0 = time.time(); done = 0; failed = 0

    def work(row):
        prompt = build_prompt(args.stage, row)
        try:
            return call_llm(prompt, args.provider, api_key)
        except Exception as e:
            return {'id': row[0], 'error': str(e)[:80]}

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
