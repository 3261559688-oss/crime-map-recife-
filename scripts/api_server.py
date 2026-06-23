#!/usr/bin/env python3
"""
Nearby Crime Events API
========================
零依赖 HTTP 服务（Python stdlib），提供：

GET  /api/health                          → 健康检查
GET  /api/whereami                        → 解析当前 IP（mock，预留对接公司 IP 接口）
POST /api/nearby                          → 查附近事件
     body: {"lat": -23.55, "lng": -46.63, "radius_km": 10, "limit": 50}
GET  /api/nearby?lat=&lng=&radius_km=&limit=&types=
                                          → 同上 GET 版（方便浏览器直测）

启动：
    python3 scripts/api_server.py --port 8787 --db data/crime_map.db
"""
import argparse
import json
import math
import os
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# ============ Mock IP 接口（预留对接公司接口） ============
# 当用户给来真实 IP 解析接口后，把这里换掉即可
def resolve_ip_mock(ip: str) -> dict:
    """Mock：默认返回圣保罗市中心。预留公司 IP 接口对接位"""
    # 简单 mock：根据 IP 前缀返回不同城市（演示用）
    presets = {
        '127': {'lat': -23.5505, 'lng': -46.6333, 'city': 'São Paulo', 'state': 'SP', 'source': 'mock-localhost'},
        '10':  {'lat': -22.9068, 'lng': -43.1729, 'city': 'Rio de Janeiro', 'state': 'RJ', 'source': 'mock-internal'},
        '192': {'lat': -8.0476,  'lng': -34.8770, 'city': 'Recife', 'state': 'PE', 'source': 'mock-private'},
    }
    prefix = ip.split('.')[0] if ip else '127'
    return presets.get(prefix, presets['127'])

# 真实接口对接位（用户给来后替换）
def resolve_ip_real(ip: str) -> dict:
    """TODO: 用户提供 IP 解析接口后替换这里。
    预期返回 {lat, lng, city, state}
    """
    # import urllib.request
    # url = f"https://你的IP接口/lookup?ip={ip}"
    # ...
    return resolve_ip_mock(ip)

# ============ 距离计算 ============
def haversine_km(lat1, lng1, lat2, lng2):
    """Haversine 距离公式，返回千米"""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# ============ 数据查询 ============
class NearbyService:
    def __init__(self, db_path: str):
        self.db_path = db_path
        # 把全部事件预加载到内存（< 5000 条，<10MB），毫秒级响应
        self._events = []
        self._load()

    def _load(self):
        if not os.path.exists(self.db_path):
            print(f"⚠️  数据库不存在: {self.db_path}", file=sys.stderr)
            return
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("""
                SELECT event_id, title, 
                       COALESCE(llm_b_type, crime_type) AS type,
                       COALESCE(llm_c_state, state) AS state,
                       COALESCE(llm_c_city, city) AS city,
                       llm_c_neighbor AS neighborhood,
                       lat, lng, news_url, source_media, pub_ts,
                       description
                FROM dwd_intl_crime_incident_di
                WHERE COALESCE(llm_a_is_crime, 1) = 1
                  AND lat IS NOT NULL AND lng IS NOT NULL
            """).fetchall()
            self._events = [dict(r) for r in rows]
            print(f"✅ 已加载 {len(self._events)} 条事件到内存")
        finally:
            conn.close()

    def reload(self):
        """供 cron / pipeline 跑完后调用，热更新内存"""
        self._load()

    def nearby(self, lat: float, lng: float, radius_km: float = 10,
               limit: int = 50, types: list = None) -> dict:
        results = []
        types_set = set(types) if types else None
        for ev in self._events:
            if types_set and ev.get('type') not in types_set:
                continue
            d = haversine_km(lat, lng, ev['lat'], ev['lng'])
            if d <= radius_km:
                ev2 = dict(ev)
                ev2['distance_km'] = round(d, 3)
                # description 太长，截短
                if ev2.get('description'):
                    ev2['description'] = ev2['description'][:200]
                results.append(ev2)
        results.sort(key=lambda x: x['distance_km'])
        return {
            'count': len(results),
            'returned': min(len(results), limit),
            'radius_km': radius_km,
            'center': {'lat': lat, 'lng': lng},
            'events': results[:limit],
        }

# ============ HTTP Handler ============
SERVICE: NearbyService = None  # 模块级单例（启动时赋值）

class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # 简洁日志
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {self.command} {self.path} → {args[1] if len(args)>1 else ''}\n")

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._json({'ok': True})

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path == '/api/health':
            return self._json({
                'ok': True,
                'events_loaded': len(SERVICE._events),
                'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            })

        if u.path == '/api/whereami':
            ip = (self.headers.get('X-Real-IP') or
                  self.headers.get('X-Forwarded-For', '').split(',')[0].strip() or
                  self.client_address[0])
            loc = resolve_ip_real(ip)
            return self._json({'ip': ip, **loc})

        if u.path == '/api/nearby':
            try:
                lat = float(q.get('lat', [0])[0])
                lng = float(q.get('lng', [0])[0])
            except (ValueError, IndexError):
                return self._json({'error': 'lat & lng required'}, 400)
            radius = float(q.get('radius_km', [10])[0])
            limit = int(q.get('limit', [50])[0])
            types = q.get('types', [None])[0]
            types = types.split(',') if types else None
            return self._json(SERVICE.nearby(lat, lng, radius, limit, types))

        if u.path == '/api/reload':
            SERVICE.reload()
            return self._json({'ok': True, 'events_loaded': len(SERVICE._events)})

        return self._json({'error': 'not found',
                           'endpoints': ['/api/health', '/api/whereami',
                                         '/api/nearby?lat=&lng=&radius_km=', '/api/reload']}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        ln = int(self.headers.get('Content-Length', 0))
        try:
            data = json.loads(self.rfile.read(ln).decode('utf-8')) if ln else {}
        except json.JSONDecodeError:
            return self._json({'error': 'invalid JSON'}, 400)

        if u.path == '/api/nearby':
            lat = data.get('lat')
            lng = data.get('lng')
            if lat is None or lng is None:
                return self._json({'error': 'lat & lng required'}, 400)
            radius = float(data.get('radius_km', 10))
            limit = int(data.get('limit', 50))
            types = data.get('types')
            return self._json(SERVICE.nearby(float(lat), float(lng), radius, limit, types))

        return self._json({'error': 'not found'}, 404)

# ============ 入口 ============
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8787)
    ap.add_argument('--host', default='0.0.0.0')
    ap.add_argument('--db', default='data/crime_map.db')
    args = ap.parse_args()

    global SERVICE
    SERVICE = NearbyService(args.db)

    httpd = ThreadingHTTPServer((args.host, args.port), APIHandler)
    print(f"🚀 Nearby API 启动: http://{args.host}:{args.port}")
    print(f"   测试:")
    print(f"   curl http://localhost:{args.port}/api/health")
    print(f"   curl http://localhost:{args.port}/api/whereami")
    print(f"   curl 'http://localhost:{args.port}/api/nearby?lat=-23.5505&lng=-46.6333&radius_km=5'")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 关闭")

if __name__ == '__main__':
    main()
