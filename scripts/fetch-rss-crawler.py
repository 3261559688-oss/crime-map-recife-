#!/usr/bin/env python3
"""
巴西犯罪新闻爬虫 + LLM 提取 + 经纬度
依赖: pip install feedparser openai requests beautifulsoup4 geopy

工作流:
1. 抓 RSS feed 拿到本周犯罪相关新闻
2. 用 LLM 从标题/正文提取：事件类型/地点/时间
3. 用 Geopy 把地址转经纬度
4. 输出 data.json 给 H5
"""

import feedparser
import requests
import json
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from geopy.geocoders import Nominatim
import time
import os

# ====== 配置 ======
RSS_FEEDS = [
    {"name": "G1 PE",       "url": "https://g1.globo.com/rss/g1/pe/pernambuco/"},
    {"name": "NE10",        "url": "https://www.ne10.uol.com.br/feed/"},
    {"name": "JC Online",   "url": "https://jc.ne10.uol.com.br/feed/"},
    {"name": "Diario PE",   "url": "https://www.diariodepernambuco.com.br/rss/ultimas.xml"},
    {"name": "Folha PE",    "url": "https://www.folhape.com.br/rss/"},
]

# 犯罪关键词（葡语）
CRIME_KEYWORDS = {
    "roubo":  ["roubo", "assalto", "assaltado", "assaltante", "roubado", "à mão armada"],
    "furto":  ["furto", "furtado", "furtaram"],
}

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")  # 设置环境变量
TARGET_CITY    = "Recife"

# ====== 第 1 步：抓 RSS ======
def fetch_rss_articles():
    """抓取所有 RSS feed 的最新文章"""
    all_articles = []
    for feed in RSS_FEEDS:
        print(f"📰 Fetching {feed['name']}...")
        try:
            d = feedparser.parse(feed['url'])
            for entry in d.entries[:30]:  # 每个源最多 30 条
                all_articles.append({
                    "source": feed['name'],
                    "title": entry.get('title', ''),
                    "summary": entry.get('summary', ''),
                    "link": entry.get('link', ''),
                    "published": entry.get('published', ''),
                })
        except Exception as e:
            print(f"  ❌ Failed: {e}")
    print(f"✅ Total articles: {len(all_articles)}")
    return all_articles

# ====== 第 2 步：过滤犯罪新闻 ======
def filter_crime_articles(articles):
    """关键词过滤 + 城市过滤"""
    crime_articles = []
    for art in articles:
        text = (art['title'] + " " + art['summary']).lower()
        
        # 必须提到 Recife
        if TARGET_CITY.lower() not in text:
            continue
        
        # 必须包含犯罪关键词
        crime_type = None
        for ctype, keywords in CRIME_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                crime_type = ctype
                break
        
        if crime_type:
            art['crime_type'] = crime_type
            crime_articles.append(art)
    
    print(f"🚨 Crime articles: {len(crime_articles)}")
    return crime_articles

# ====== 第 3 步：LLM 提取结构化信息 ======
def extract_with_llm(article):
    """用 OpenAI/Claude 从文章提取 location + 简短描述"""
    if not OPENAI_API_KEY:
        # 没 API key 就用 fallback：从标题提取
        return extract_with_regex(article)
    
    prompt = f"""从下面这条巴西葡语犯罪新闻里提取信息，返回纯 JSON：

标题: {article['title']}
摘要: {article['summary']}

返回格式:
{{
  "location_name": "具体街道/广场/商业区名（如 'Av. Boa Viagem'）",
  "neighborhood": "区/邻里名（如 'Boa Viagem'）",
  "short_description": "一句话葡语描述（< 80 字符）",
  "is_violent": true/false
}}

如果无法提取地点，location_name 返回 null。
只返回 JSON，不要其他文字。"""

    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            }
        )
        text = r.json()['choices'][0]['message']['content']
        # 抠 JSON
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"  LLM error: {e}")
    return extract_with_regex(article)

def extract_with_regex(article):
    """fallback: 正则提取地名"""
    title = article['title']
    # 匹配 "na Av. XXX", "em XXX", "no XXX"
    patterns = [
        r'(?:na|no|em)\s+(Av\.\s*[A-Za-zÀ-ÿ\s]+?)(?:\s|,|$)',
        r'(?:no|na)\s+(bairro\s+\w+)',
        r'(?:em|no|na)\s+([A-Z][a-zÀ-ÿ]+(?:\s+[A-Z][a-zÀ-ÿ]+){0,2})',
    ]
    location = None
    for p in patterns:
        m = re.search(p, title)
        if m:
            location = m.group(1).strip()
            break
    return {
        "location_name": location,
        "neighborhood": None,
        "short_description": article['title'][:80],
        "is_violent": "armada" in title.lower() or "esfaqueado" in title.lower()
    }

# ====== 第 4 步：地址 → 经纬度 ======
def geocode_address(address, city="Recife, Pernambuco, Brazil"):
    """用 Nominatim (OpenStreetMap) 免费 geocode"""
    if not address:
        return None, None
    
    geolocator = Nominatim(user_agent="crime_map_recife/1.0")
    try:
        full_addr = f"{address}, {city}"
        loc = geolocator.geocode(full_addr, timeout=10)
        if loc:
            return loc.latitude, loc.longitude
    except Exception as e:
        print(f"  Geocode error: {e}")
    return None, None

# ====== 第 5 步：组装最终 data.json ======
def build_incident(article, idx):
    """组装单个 incident"""
    print(f"📍 Processing {idx+1}: {article['title'][:50]}...")
    
    # LLM 提取
    extracted = extract_with_llm(article)
    location_name = extracted.get('location_name')
    
    if not location_name:
        print("  ⚠️ No location, skip")
        return None
    
    # Geocode
    lat, lng = geocode_address(location_name)
    time.sleep(1)  # Nominatim 限流：1 req/sec
    
    if not lat or not lng:
        print(f"  ⚠️ Geocode failed for: {location_name}")
        return None
    
    # 计算相对时间
    pub_str = article.get('published', '')
    try:
        pub_time = datetime.strptime(pub_str[:25], "%a, %d %b %Y %H:%M:%S")
        hours_ago = int((datetime.now() - pub_time).total_seconds() / 3600)
    except:
        hours_ago = 1
    
    return {
        "id": f"rec_{idx+1:03d}",
        "type": article['crime_type'],
        "title": article['title'],
        "description": extracted.get('short_description', ''),
        "location_name": location_name,
        "lat": lat,
        "lng": lng,
        "video_url": "",  # RSS 通常没视频
        "thumbnail_url": f"https://picsum.photos/seed/rec{idx+1}/400/300",
        "duration_str": "0:00",
        "author_name": article['source'],
        "author_avatar_letter": article['source'][0],
        "publish_time_iso": datetime.now().isoformat(),
        "publish_time_relative": f"há {hours_ago}h" if hours_ago < 24 else f"há {hours_ago//24}d",
        "verified": True,
        "is_pulse": extracted.get('is_violent', False),
        "source_url": article['link']
    }

def main():
    # 1. 抓
    articles = fetch_rss_articles()
    
    # 2. 过滤
    crime_articles = filter_crime_articles(articles)
    
    # 3-5. 每条提取 + geocode
    incidents = []
    for i, art in enumerate(crime_articles):
        inc = build_incident(art, len(incidents))
        if inc:
            incidents.append(inc)
        if len(incidents) >= 30:
            break
    
    # 输出
    output = {
        "city": {
            "id": "recife",
            "name": "Recife, PE",
            "country": "BR",
            "lat": -8.0476,
            "lng": -34.8770,
            "timezone": "America/Recife"
        },
        "meta": {
            "last_updated": datetime.now().isoformat() + "-03:00",
            "data_source": "rss_auto",
            "total_count": len(incidents),
            "period_days": 7
        },
        "incidents": incidents
    }
    
    output_path = "../public/data.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 完成! 写入 {len(incidents)} 条 incidents 到 {output_path}")

if __name__ == "__main__":
    main()
