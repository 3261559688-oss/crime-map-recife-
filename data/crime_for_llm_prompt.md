# LLM 校验 Prompt 模板

你是巴西新闻分析师，任务：判断每条新闻是否真的为犯罪事件，并给出准确的发生地。

【背景】下表是从巴西 50+ 葡语媒体 RSS 抓取的 2547 条新闻，我用关键词初步打了标，但准确度只有 28%（71% 是 default 兜底），需要你帮我洗一遍。

【输入字段】
  id            事件唯一 ID（必须原样返回）
  title         葡语标题
  source        来源媒体
  link          原文链接
  current_state 关键词解析的州（可能错）
  current_city  关键词解析的城市（可能错）
  current_type  关键词解析的犯罪类型（可能错）

【你要做的事】
对每条新闻，输出以下 JSON 字段：
  - llm_is_crime  : true/false（是不是真犯罪事件？政治/娱乐/经济新闻 = false）
  - llm_score     : 0-100（你的置信度）
  - llm_state     : 2 字母州代码（SP/RJ/PE/BA 等 27 个，全国性新闻填 BR）
  - llm_city      : 城市名
  - llm_neighbor  : 街区（如标题提及，否则留空）
  - llm_type      : 犯罪类型枚举（13 选 1，下方说明）
  - llm_reason    : 一句话理由（中文）

【犯罪类型枚举】
  homicidio  凶杀 / 谋杀 / 致死
  roubo      抢劫（使用暴力或威胁）
  furto      盗窃（无暴力）
  estupro    强奸 / 性侵
  trafico    毒品贩运
  sequestro  绑架
  violencia  暴力（殴打、冲突、未致死）
  policia    警方行动（缉捕、警枪、警员）
  faccao    派系（CV/PCC/ADA 等帮派活动）
  fraude    诈骗
  veiculo   车辆（劫车/盗车/车祸）
  menor     未成年涉案
  outros    其他犯罪
  NAO_CRIME 非犯罪事件（政治/娱乐/经济等）

【输出格式】
对每条记录输出 1 行 JSON（NDJSON 格式），例如：
{"id":"inc_001","llm_is_crime":false,"llm_score":95,"llm_state":"RJ","llm_city":"Rio de Janeiro","llm_neighbor":"","llm_type":"NAO_CRIME","llm_reason":"政治新闻：军方调查 CV 与 PCC 的关联"}

【特别注意】
1. 严格按照 id 顺序输出，不要漏行
2. 政治新闻（如 Trump/Lula/总统/参议院/选举）→ NAO_CRIME
3. 娱乐/体育/财经 → NAO_CRIME
4. 标题提及城市的，以标题为准；没提的，看 link URL
5. CV / PCC / ADA / TCP / Comando Vermelho / Primeiro Comando 都是巴西帮派
6. "Operação policial" 是警方行动 → policia
7. 输出前不要任何前言，直接出 JSON

下面开始处理数据，共 2547 条：

---

# 数据表请粘贴 crime_for_llm.csv 内容
