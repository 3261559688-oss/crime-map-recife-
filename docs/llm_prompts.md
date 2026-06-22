# 🤖 LLM 三阶段 Prompt 模板（巴西犯罪地图）

> 三阶段串联工作流：A 真伪 → B 类型 → C 地理
> 每个 Prompt 单独使用，分阶段独立调优

---

## 🅰️ Stage A：真伪校验（is_crime）

**目标**：判断这条新闻是不是真的犯罪事件，过滤掉政治/娱乐/经济等噪声。

**输入字段**：`id`, `title`, `source`, `link`

**输出 JSON 字段**：
- `is_crime`: true/false
- `score`: 0-100（置信度）
- `reason`: 一句话中文理由

### Prompt（葡萄牙语 + 中文 reason）

```
Você é analista de notícias brasileiras. Sua tarefa: identificar se uma manchete é sobre CRIME REAL ou não.

【REGRAS】
✓ É CRIME (is_crime=true):
  - Homicídio, assassinato, morte violenta
  - Roubo, furto, assalto, latrocínio
  - Estupro, abuso sexual, feminicídio
  - Tráfico de drogas, apreensão de drogas
  - Sequestro, cárcere privado
  - Operação policial, prisão, captura
  - Atividade de facção (CV, PCC, ADA, TCP)
  - Fraude, golpe, estelionato
  - Veículo roubado/furtado, atropelamento criminal
  - Violência doméstica, agressão
  - Crime contra menor

✗ NÃO É CRIME (is_crime=false):
  - Política (eleição, governo, presidente, ministro, congresso)
  - Esportes (futebol, copa, atleta, jogo)
  - Economia (bolsa, dólar, inflação, mercado)
  - Entretenimento (novela, cantor, celebridade, BBB)
  - Clima, ciência, saúde geral
  - Crime já julgado historicamente (não é evento atual)
  - Opinião/análise sem fato novo

【FORMATO】
Responda APENAS JSON, sem markdown:
{"id":"<id_original>","is_crime":true|false,"score":<0-100>,"reason":"<理由中文,30字内>"}

【EXEMPLOS】

Manchete: "Homem é morto a tiros na Zona Sul de São Paulo"
→ {"id":"x","is_crime":true,"score":95,"reason":"明确凶杀案，地点明确"}

Manchete: "Lula se reúne com Putin para discutir BRICS"
→ {"id":"x","is_crime":false,"score":98,"reason":"政治新闻，非犯罪"}

Manchete: "PCC controla tráfico em Manaus, diz polícia"
→ {"id":"x","is_crime":true,"score":92,"reason":"贩毒+派系活动"}

Manchete: "Trump ameaça impor sanções ao Brasil"
→ {"id":"x","is_crime":false,"score":97,"reason":"国际政治新闻"}

Manchete: "Tribunal condena ex-governador por corrupção"
→ {"id":"x","is_crime":false,"score":75,"reason":"司法历史事件，非新发犯罪"}

---

【ENTRADA】
id: {id}
title: {title}
source: {source}
link: {link}

【SAÍDA】
```

**模型推荐**：DeepSeek（二分类够用，¥0.5/1000 条）
**Token 估算**：~250 输入 + ~50 输出 / 条

---

## 🅱️ Stage B：类型分类（type）

**目标**：在已确认为犯罪的新闻里，重新打 13 类标签。

**触发条件**：`is_crime=true`（Stage A 通过的）

**输入字段**：`id`, `title`, `link`, `current_type`（关键词原打标，供 LLM 参考对比）

**输出 JSON 字段**：
- `type`: 13 类枚举之一
- `score`: 0-100
- `changed`: bool（是否与 current_type 不同）
- `reason`: 一句话中文

### Prompt

```
Você é especialista em classificação de crimes no Brasil. A notícia já foi confirmada como CRIME REAL. Classifique o TIPO.

【13 TIPOS DISPONÍVEIS】
homicidio   凶杀/谋杀（含 morte/assassinato/executado/morto a tiros/latrocínio）
roubo       抢劫（com violência/ameaça：assalto/arrastão/roubo armado）
furto       盗窃（sem violência：furto simples/qualificado）
estupro     强奸（estupro/abuso sexual/violência sexual）
trafico     贩毒（tráfico de drogas/apreensão de cocaína/maconha/crack）
sequestro   绑架（sequestro/cárcere privado/rapto/extorsão mediante sequestro）
violencia   暴力（agressão/espancamento/briga/feminicídio sem morte ainda）
policia     警方行动（operação policial/PM prende/captura/apreensão）
faccao      派系（CV, PCC, ADA, TCP, Comando Vermelho, Primeiro Comando）
fraude      诈骗（golpe/estelionato/pirâmide/fraude bancária）
veiculo     车辆相关（carro roubado/atropelamento criminal/racha）
menor       未成年涉案（criança/adolescente vítima ou autor）
outros      其他犯罪（não se encaixa nas 12 anteriores）

【REGRAS DE PRIORIDADE】
1. Se manchete tem MORTE → homicidio (mesmo que envolva facção, escolha o crime principal)
2. Se é OPERAÇÃO POLICIAL como evento principal → policia
3. Facção como CONTEXTO (ex: "PCC mata rival") → homicidio
   Facção como AÇÃO (ex: "PCC domina região") → faccao
4. Roubo COM violência → roubo; SEM violência → furto
5. Sempre prefira o crime MAIS GRAVE se houver múltiplos

【FORMATO】
Responda APENAS JSON:
{"id":"<id>","type":"<um dos 13>","score":<0-100>,"changed":true|false,"reason":"<中文 30字>"}

【EXEMPLOS】

Manchete: "Operação da PM apreende 50kg de cocaína em Cuiabá"
current_type: trafico
→ {"id":"x","type":"trafico","score":92,"changed":false,"reason":"贩毒+警方操作，主要是贩毒"}

Manchete: "PCC executa 3 rivais em Rio Branco"
current_type: faccao
→ {"id":"x","type":"homicidio","score":95,"changed":true,"reason":"主要犯罪是凶杀，派系是背景"}

Manchete: "Bandidos invadem casa e furtam joias no Rio"
current_type: roubo
→ {"id":"x","type":"furto","score":85,"changed":true,"reason":"入室盗窃无暴力"}

Manchete: "Adolescente é morto em chacina em Belém"
current_type: homicidio
→ {"id":"x","type":"homicidio","score":90,"changed":false,"reason":"未成年凶杀，优先选凶杀"}

---

【ENTRADA】
id: {id}
title: {title}
link: {link}
current_type (palavra-chave, pode estar errado): {current_type}

【SAÍDA】
```

**模型推荐**：DeepSeek 或 GPT-4o-mini
**Token 估算**：~350 输入 + ~60 输出 / 条

---

## 🅲️ Stage C：地理校正（state/city/neighborhood）

**目标**：在已确认为犯罪的新闻里，准确识别发生州/市/街区。

**触发条件**：`is_crime=true`

**输入字段**：`id`, `title`, `link`, `current_state`, `current_city`, `city_method`

**输出 JSON 字段**：
- `state`: 2 字母州代码或 BR
- `city`: 城市名
- `neighborhood`: 街区名或 ''
- `score`: 0-100
- `evidence`: 标题里的证据片段
- `reason`: 一句话中文

### Prompt

```
Você é especialista em geografia do Brasil. A notícia foi confirmada como CRIME. Identifique ONDE o crime aconteceu.

【ESTADOS BRASILEIROS（27 siglas + BR）】
AC Acre        | AL Alagoas      | AP Amapá       | AM Amazonas
BA Bahia       | CE Ceará        | DF Brasília    | ES Espírito Santo
GO Goiás       | MA Maranhão     | MT Mato Grosso | MS Mato Grosso do Sul
MG Minas Gerais| PA Pará         | PB Paraíba     | PR Paraná
PE Pernambuco  | PI Piauí        | RJ Rio de Janeiro | RN Rio Grande do Norte
RS Rio Grande do Sul | RO Rondônia | RR Roraima  | SC Santa Catarina
SP São Paulo   | SE Sergipe      | TO Tocantins
BR (use quando crime é nacional ou estado desconhecido)

【REGRAS DE PRIORIDADE】
1. Cidade EXPLÍCITA na manchete → use ela
   Ex: "morto em Recife" → state=PE, city=Recife
2. Se manchete cita BAIRRO famoso → identificar pela cidade
   Ex: "Copacabana" → RJ/Rio de Janeiro
   Ex: "Liberdade" → SP/São Paulo (Bairro)
3. URL contém /sp/santos/ → state=SP, city=Santos
4. Se source tem viés regional (G1 PE → Pernambuco), use como dica
5. NÃO confie em current_state se city_method='default' (alta chance de erro)
6. Se manchete cita MÚLTIPLAS cidades, escolha onde o CRIME aconteceu
   Ex: "Foragido de SP é preso no RJ" → state=RJ
7. Cobertura nacional (Brasília + análise) → state=BR
8. Bairros do Rio (Rocinha, Maré, Complexo do Alemão, Vidigal, Copacabana, Ipanema, Tijuca) → RJ
   Bairros de SP (Liberdade, Sé, Vila Madalena, Pinheiros, Mooca, Itaim, Brás) → SP
   Bairros de Recife (Boa Viagem, Casa Forte, Madalena, Pina) → PE

【EVIDÊNCIA】
Cite a frase ou palavra da manchete que prova sua decisão.

【FORMATO】
Responda APENAS JSON:
{"id":"<id>","state":"<2letras>","city":"<cidade>","neighborhood":"<bairro ou ''>","score":<0-100>,"evidence":"<frase>","reason":"<中文 30字>"}

【EXEMPLOS】

Manchete: "Tiroteio na Rocinha deixa 2 mortos"
current_state: BR (city_method=default)
→ {"id":"x","state":"RJ","city":"Rio de Janeiro","neighborhood":"Rocinha","score":95,"evidence":"Rocinha","reason":"Rocinha 是 RJ 著名贫民窟"}

Manchete: "Foragido de São Paulo é capturado em Manaus pela PM"
current_state: SP
→ {"id":"x","state":"AM","city":"Manaus","neighborhood":"","score":92,"evidence":"capturado em Manaus","reason":"被捕地在 Manaus(AM)"}

Manchete: "PM apreende 30kg de cocaína em operação no bairro Madalena, Recife"
current_state: PE
→ {"id":"x","state":"PE","city":"Recife","neighborhood":"Madalena","score":98,"evidence":"Madalena, Recife","reason":"明确街区+城市"}

Manchete: "Brasil registra alta de homicídios em 2025, diz Anuário"
current_state: default
→ {"id":"x","state":"BR","city":"","neighborhood":"","score":80,"evidence":"Brasil","reason":"全国性统计新闻"}

Manchete: "Empresário é morto a tiros"
current_state: default
→ {"id":"x","state":"BR","city":"","neighborhood":"","score":30,"evidence":"","reason":"标题缺地理信息，置信度低"}

---

【ENTRADA】
id: {id}
title: {title}
link: {link}
source: {source}
current_state (pode estar errado): {current_state}
current_city: {current_city}
city_method: {city_method}   ← 注意：default 表示原值是兜底，最可能错

【SAÍDA】
```

**模型推荐**：GPT-4o-mini（地理推理稍强）或 DeepSeek
**Token 估算**：~600 输入 + ~80 输出 / 条

---

## 📊 三阶段对比

| 阶段 | 任务 | 输入条数 | Token/条 | 模型推荐 | 单条成本 |
|---|---|---|---|---|---|
| 🅰️ A | 真伪 | 2542 全量 | ~300 | DeepSeek | ¥0.0003 |
| 🅱️ B | 类型 | ~2344（A 过滤后） | ~410 | DeepSeek | ¥0.0004 |
| 🅲️ C | 地理 | ~2344 | ~680 | DeepSeek | ¥0.0006 |
| **总计** | - | - | - | - | **~¥3.5** |

**对比一次问 7 个字段**：~¥4，但准确率从 75% 提到 90%+

---

## 🚀 Luigi 工作流图

```
FetchRSS
   ↓
BuildSQLite
   ↓
LLMStageA_IsCrime    ← 跑 2542 条 → 标记 is_crime
   ↓
LLMStageB_Type       ← 只跑 is_crime=true 的 2344 条
   ↓
LLMStageC_Geo        ← 只跑 is_crime=true 的 2344 条
   ↓
MergeFinalReport
```

任何一步失败：
- ✅ 已成功的 stage 不重跑
- ✅ 自动从失败点继续
- ✅ Luigi web UI 可视化

---

## 📋 使用方式（伪代码）

```bash
# 跑单阶段
python3 scripts/luigi_pipeline.py --stage a
python3 scripts/luigi_pipeline.py --stage b
python3 scripts/luigi_pipeline.py --stage c

# 跑全流程（Luigi 自动按依赖顺序）
python3 scripts/luigi_pipeline.py --target FinalReport

# 看 Luigi 可视化 DAG
luigid &   # 启动 web UI
open http://localhost:8082
```

---

*— LLM 三阶段 Prompt v1.0 —*
*位置: ~/Desktop/crime-map-recife/docs/llm_prompts.md*
