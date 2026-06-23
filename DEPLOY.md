# Crime Map 站内部署指南

## 🎯 项目架构
```
┌─────────────────────────────────────────┐
│  Docker 容器（KStation/KCS）             │
│  ├─ scripts/api_server.py  :8787        │  ← 前台进程，提供 API + 静态前端
│  ├─ cron 守护（每 30 分钟）              │  ← 跑 pipeline.sh（fetch+LLM）
│  ├─ /app/data/crime_map.db (持久卷)      │  ← SQLite 主库
│  └─ /app/public/                        │  ← 前端静态资源
└─────────────────────────────────────────┘
       ↓
   万擎 API（内网）
       ↓
   公司 IP 解析接口（内网）
```

## 🚀 站内部署 — KStation 路径（推荐）

### 1️⃣ 推代码到 KDev GitLab
```bash
git remote add kdev https://kdev.corp.kuaishou.com/git/kwai/CoreFeature/kwai-local-tab-crime.git
git push kdev main
```

### 2️⃣ KStation 创建项目
访问 https://kstation.corp.kuaishou.com → 新建项目
- 类型：**Web 应用** + **定时任务**
- 仓库：选 `kwai-local-tab-crime`
- 构建方式：**Dockerfile**（仓库里已有）

### 3️⃣ 配环境变量
在 KStation 项目设置中添加：
| Key | Value |
|---|---|
| `WQ_API_KEY` | 你的万擎 Key |
| `WQ_API_URL` | https://wanqing-api.corp.kuaishou.com/api/gateway/v1/messages |
| `WQ_MODEL` | ep-7zifa0-1777001276406194677 |
| `IP_LOOKUP_URL` | （IP 接口 URL，等接口给来后填） |

### 4️⃣ 配持久卷
- 挂载点：`/app/data`
- 大小：1GB（SQLite 30 万条事件 < 100MB）

### 5️⃣ 暴露端口
- 容器端口：`8787`
- 公网/内网：内网域名（自动分配 `*.kstation.corp.kuaishou.com`）

### 6️⃣ 部署 → 验收
```bash
# 健康检查
curl https://你的域名/api/health
# 应返回 {"ok":true,"events_loaded":2102,...}

# 首页
curl https://你的域名/index.html

# 附近事件
curl 'https://你的域名/api/nearby?lat=-23.55&lng=-46.63&radius_km=5'
```

---

## 🛠️ 本地 Docker 测试（部署前）

```bash
# 构建
docker build -t crime-map .

# 运行
docker run -d --name cm \
  -p 8787:8787 \
  -e WQ_API_KEY="你的key" \
  -v $(pwd)/data:/app/data \
  crime-map

# 看日志
docker logs -f cm

# 测试
curl http://localhost:8787/api/health
```

---

## 📋 文件清单

| 文件 | 作用 |
|---|---|
| `Dockerfile` | 容器镜像定义 |
| `requirements.txt` | Python 依赖 |
| `.env.example` | 环境变量模板 |
| `scripts/entrypoint.sh` | 容器启动脚本 |
| `scripts/crontab.txt` | 定时任务配置 |
| `scripts/pipeline.sh` | 主流水线（fetch+LLM+导出） |
| `scripts/api_server.py` | API 服务（health/whereami/nearby/reload） |

---

## 🔌 IP 解析接口对接位

`scripts/api_server.py` 第 36-42 行 `resolve_ip_real()`：
```python
def resolve_ip_real(ip: str) -> dict:
    url = os.environ['IP_LOOKUP_URL'] + '?ip=' + ip
    with urllib.request.urlopen(url, timeout=5) as r:
        d = json.loads(r.read())
    return {'lat': d['lat'], 'lng': d['lng'], 
            'city': d['city'], 'state': d['state']}
```

---

## ⏰ 巡检节奏

每 30 分钟自动跑一次 `pipeline.sh`：
- 拉 RSS（30 秒）
- 增量入库（5 秒）
- LLM A/B/C 三段（仅跑新增的 NULL 字段，约 5-10 分钟）
- 通知 API 热更新内存

---

## 🆘 常见问题

**Q: SQLite 在容器重启后会丢吗？**
A: 不会，挂载在持久卷 `/app/data` 上。

**Q: LLM 失败了怎么办？**
A: pipeline.sh 用 `|| true` 容错，下次轮询自动重跑（NULL 字段优先）。

**Q: 怎么手动触发一次更新？**
A: `kubectl exec` 进容器后 `bash /app/scripts/pipeline.sh`。

**Q: 内存够吗？**
A: 全部 ~5000 条事件加载到内存约 10MB，分配 256MB 足够。
