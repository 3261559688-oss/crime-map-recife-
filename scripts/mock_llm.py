#!/usr/bin/env python3
"""
模拟 LLM 输出（用规则模拟真实 LLM 的判断）
============================================================
读 data/crime_for_llm.csv → 生成 data/crime_llm_result.ndjson
============================================================
真实场景：你把 CSV 给 ChatGPT/DeepSeek，LLM 会输出同样格式的 NDJSON。
本脚本只是替你"假装跑了一遍 LLM"，让你看到完整闭环。
"""
import json
import re
import csv
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

NON_CRIME = ['lula','bolsonaro','trump','presidente','eleição','eleicao','senado','câmara','camara',
             'congresso','dólar','dolar','bolsa','ibovespa','copa','futebol','novela','fofoca',
             'cantora','cantor','astrolog','horóscopo','horoscopo','enem','vestibular','bbb',
             'big brother','aquecimento global','clima','meteorolog','reforma','impeachment',
             'governador','prefeito','ministr','tribunal']

CRIME_KW = {
  'homicidio': ['mort','assassin','homicíd','homicid','executad','tiros','mata','matou','morrer'],
  'roubo':     ['roub','assalt','arrasta'],
  'furto':     ['furt'],
  'estupro':   ['estupr','violência sexual','abuso sexual'],
  'trafico':   ['tráfico','trafico','droga','cocaína','cocaina','maconha','crack'],
  'sequestro': ['sequestr','rapt','cárcere','carcere'],
  'violencia': ['agress','espanc','briga','luta corporal','feminicíd','feminicid'],
  'policia':   ['operação polic','operacao polic','pm prende','polícia prende','policia prende','captur','apreens'],
  'faccao':    [' cv ','pcc','ada ','tcp','comando vermelho','primeiro comando','facção','faccao'],
  'fraude':    ['fraude','golpe','estelionat','pirâmide','piramide'],
  'veiculo':   ['carro roub','moto roub','veículo roub','veiculo roub','batida','colisão','colisao','atropela'],
  'menor':     ['adolescent','menor de idade','criança morta','crianca morta'],
}

# 巴西州大致识别（标题包含哪个州/城市关键词）
STATE_HINTS = {
  'SP':['sp','são paulo','sao paulo','santos','campinas','guarulhos','osasco','sorocaba'],
  'RJ':['rj','rio de janeiro','niterói','niteroi','duque de caxias','rio'],
  'MG':['mg','minas gerais','belo horizonte','contagem','uberlândia','uberlandia'],
  'BA':['ba','bahia','salvador','feira de santana','itabuna'],
  'PE':['pe','pernambuco','recife','olinda','jaboatão','jaboatao','caruaru'],
  'CE':['ce','ceará','ceara','fortaleza','caucaia'],
  'RS':['rs','rio grande do sul','porto alegre'],
  'PR':['pr','paraná','parana','curitiba','londrina','maringá','maringa'],
  'GO':['go','goiás','goias','goiânia','goiania'],
  'PA':['pa','pará','para','belém','belem'],
  'MA':['ma','maranhão','maranhao','são luís','sao luis'],
  'AM':['am','amazonas','manaus'],
  'DF':['df','brasília','brasilia','distrito federal'],
  'ES':['es','espírito santo','espirito santo','vitória','vitoria'],
  'SC':['sc','santa catarina','florianópolis','florianopolis','joinville'],
  'PB':['pb','paraíba','paraiba','joão pessoa','joao pessoa','campina grande'],
  'AL':['al','alagoas','maceió','maceio'],
  'PI':['pi','piauí','piaui','teresina'],
  'RN':['rn','rio grande do norte','natal'],
  'MT':['mt','mato grosso','cuiabá','cuiaba'],
  'MS':['ms','mato grosso do sul','campo grande'],
  'SE':['se','sergipe','aracaju'],
  'RO':['ro','rondônia','rondonia','porto velho'],
  'TO':['to','tocantins','palmas'],
  'AC':['ac','acre','rio branco'],
  'AP':['ap','amapá','amapa','macapá','macapa'],
  'RR':['rr','roraima','boa vista'],
}

def mock_llm(item):
    title = (item['title'] or '').lower()
    src   = (item.get('source','') or '').lower()
    link  = (item.get('link','') or '').lower()

    # ① 是否非犯罪
    is_non_crime = any(k in title for k in NON_CRIME)
    is_crime = not is_non_crime

    # ② 类型
    detected_type = 'outros'
    for t, kws in CRIME_KW.items():
        if any(k in title for k in kws):
            detected_type = t; break
    if not is_crime: detected_type = 'NAO_CRIME'

    # ③ 州（标题 + url 双重判断）
    detected_state = ''
    text = title + ' ' + link + ' ' + src
    for st, kws in STATE_HINTS.items():
        if any(f' {k} ' in f' {text} ' or f'/{k}/' in text or k in title.split(' ') for k in kws if len(k) > 2):
            detected_state = st; break
    if not detected_state and 'metrópoles df' in src: detected_state = 'BR'  # 全国性媒体

    # ④ 城市（粗略）
    detected_city = ''
    for st, kws in STATE_HINTS.items():
        for k in kws[1:]:  # skip 2字母代码
            if k in title:
                detected_city = k.title(); break
        if detected_city: break

    # ⑤ 街区（粗略：bairro / na / em + 大写词）
    nb_m = re.search(r'(?:bairro|comunidade|favela|na|em)\s+([A-ZÁÉÍÓÚ][a-záéíóú]+(?:\s+[A-ZÁÉÍÓÚ][a-záéíóú]+)*)', item['title'] or '')
    detected_neighbor = nb_m.group(1) if nb_m else ''

    # ⑥ 置信度（综合判断）
    score = 70
    if is_non_crime: score = 88  # 否定判断比较准
    if detected_type != 'outros' and detected_type != 'NAO_CRIME': score += 10
    if detected_state: score += 5
    if detected_city: score += 3
    score = min(score, 95)

    return {
        'id': item['id'],
        'llm_is_crime': is_crime,
        'llm_score': score,
        'llm_state': detected_state,
        'llm_city': detected_city,
        'llm_neighbor': detected_neighbor,
        'llm_type': detected_type,
        'llm_reason': '非犯罪：政治/娱乐/经济新闻' if is_non_crime else
                      f'犯罪事件，关键词匹配 {detected_type}',
        'llm_model': 'mock-rule-v1',
    }

def main():
    csv_in = ROOT/'data'/'crime_for_llm.csv'
    out = ROOT/'data'/'crime_llm_result.ndjson'
    if not csv_in.exists():
        print(f'❌ 请先运行 python3 scripts/export_for_llm.py')
        return

    items = []
    with open(csv_in, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            items.append(r)
    print(f'📦 读取 {len(items)} 条')

    print(f'🤖 开始 mock LLM 校验...')
    results = [mock_llm(x) for x in items]

    with open(out, 'w') as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    not_crime = sum(1 for r in results if not r['llm_is_crime'])
    avg_score = sum(r['llm_score'] for r in results) / len(results)
    print(f'✅ 输出: {out} ({out.stat().st_size:,} bytes)')
    print(f'   总条数: {len(results):,}')
    print(f'   判定非犯罪: {not_crime:,} ({not_crime*100/len(results):.1f}%)')
    print(f'   平均置信度: {avg_score:.1f}')

    print('\n📋 类型分布（LLM 校正后）:')
    from collections import Counter
    for t,c in Counter(r['llm_type'] for r in results).most_common():
        print(f'   {t:12} {c:>6}')

    print('\n📋 州分布（LLM 校正后）TOP 8:')
    for s,c in Counter(r['llm_state'] for r in results).most_common(8):
        print(f'   {s or "(空)":4} {c:>6}')

    print(f'\n🚀 下一步：python3 scripts/db.py merge {out}')

if __name__=='__main__':
    main()
