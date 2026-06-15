# 🚀 Crime Map Recife · 一个人上线指南

## 📁 项目结构

```
crime-map-recife/
├── public/
│   ├── index.html       # 主页面（H5 落地页）
│   └── data.json        # 数据文件（手动维护）
├── scripts/
│   └── fetch-news.js    # 数据生成脚本
├── package.json
├── vercel.json          # Vercel 部署配置
└── README.md
```

---

## 🎯 30 分钟上线（最快路径）

### Step 1: 注册账号（5 分钟）
- 注册 [GitHub](https://github.com)
- 注册 [Vercel](https://vercel.com)（用 GitHub 登录）

### Step 2: 上传到 GitHub（10 分钟）
```bash
cd /Users/dongyuhan03/Desktop/crime-map-recife

# 初始化 git
git init
git add .
git commit -m "Initial commit"

# 在 GitHub 上创建一个 repo（叫 crime-map-recife），然后：
git remote add origin https://github.com/YOUR_USERNAME/crime-map-recife.git
git branch -M main
git push -u origin main
```

### Step 3: Vercel 一键部署（5 分钟）
1. 打开 [vercel.com/new](https://vercel.com/new)
2. 选 "Import Git Repository" → 选你刚创建的 repo
3. **不需要任何配置**，直接点 "Deploy"
4. 等 30 秒，拿到 `https://crime-map-recife.vercel.app` 这种域名

### Step 4: 配置 Google Analytics（10 分钟）
1. 打开 [analytics.google.com](https://analytics.google.com)
2. 创建一个 GA4 媒体资源 → 拿到 `G-XXXXXXXXXX` ID
3. 编辑 `public/index.html`，替换两处 `G-XXXXXXXXXX`
4. `git add . && git commit -m "add ga" && git push`
5. Vercel 自动重新部署

✅ **完成！现在你有一个真实可访问的链接了**

---

## 📊 每周更新数据（30 分钟/周）

### 方式 A：手动编辑 data.json（最简单）

1. 直接编辑 `public/data.json`
2. 复制现有的 incidents 条目，改一下内容
3. `git add . && git commit -m "update data" && git push`
4. 30 秒后自动上线

### 方式 B：用脚本（推荐）

1. 编辑 `scripts/fetch-news.js`，在 `INCIDENTS_INPUT` 里填入新闻
2. 运行 `node scripts/fetch-news.js`（自动生成 data.json）
3. `git add . && git commit -m "update" && git push`

---

## 📰 数据采集来源（巴西本地）

| 来源 | 类型 | 用途 |
|---|---|---|
| [G1 Pernambuco](https://g1.globo.com/pe/pernambuco/) | 新闻网站 | 主要犯罪新闻 |
| [NE10](https://www.ne10.uol.com.br/) | 新闻网站 | Recife 本地新闻 |
| [Diario de Pernambuco](https://www.diariodepernambuco.com.br/) | 报纸 | 严肃新闻 |
| [Recife Alerta (IG)](https://instagram.com/recifealerta) | Instagram | 实时事件 |
| [JC Online](https://jc.ne10.uol.com.br/) | 新闻网站 | 综合 |
| [SSP-PE 官方](http://www.ssp.pe.gov.br/) | 政府数据 | 月报数据 |

### 经纬度获取
- 用 [Google Maps](https://maps.google.com)：右键地点 → 复制坐标
- 或 [LatLong.net](https://www.latlong.net/)：地址 → 经纬度

### 视频嵌入
- **YouTube**：用 `https://www.youtube.com/embed/VIDEO_ID` 格式
- **Instagram**：暂不支持嵌入，用截图 + YouTube 替代
- **TikTok**：`https://www.tiktok.com/embed/v2/VIDEO_ID`

---

## 🏷️ 数据字段说明

```json
{
  "id": "rec_001",                    // 唯一 ID（自增）
  "type": "roubo",                    // roubo 或 furto
  "title": "标题",                     // 必填
  "description": "描述",               // 可选
  "location_name": "Av. Boa Viagem",  // 地名（展示用）
  "lat": -8.1175,                     // 纬度（必填）
  "lng": -34.9015,                    // 经度（必填）
  "video_url": "embed URL",           // 视频嵌入 URL
  "thumbnail_url": "图片 URL",         // 缩略图
  "duration_str": "0:32",             // 时长展示
  "author_name": "G1 PE",             // 来源
  "publish_time_relative": "há 3h",   // 相对时间
  "verified": true,                   // 是否认证
  "is_pulse": true,                   // 是否高亮（突发/重大）
  "source_url": "原文链接"             // 原文
}
```

---

## ⚖️ 法务合规（巴西 LGPD）

### 必做
- [ ] 加 Cookie 提示（如果用 GA）
- [ ] 加隐私政策页面
- [ ] 视频引用合规：用 YouTube embed（合法）/ 拿到授权
- [ ] 标注信息来源（每条都加 source_url）

### 不要做
- ❌ 收集用户位置 / 个人信息
- ❌ 直接转载完整文章
- ❌ 使用受版权保护的视频

---

## 📈 监控运营

### 看数据
- Google Analytics 4：访问量 / 留存 / 行为路径
- Vercel Analytics：访问速度 / 错误率

### KPI
| 指标 | 目标 |
|---|---|
| 月活 PV | > 1000 |
| 平均停留时长 | > 60s |
| Marker 点击率 | > 30% |
| 视频打开率 | > 15% |

---

## 🔧 本地调试

```bash
# 安装 serve（一次性）
npm install -g serve

# 启动本地服务器
serve public -p 3000

# 访问 http://localhost:3000
```

---

## 🚨 紧急情况

| 问题 | 处理 |
|---|---|
| 网站打不开 | 看 Vercel 部署日志 |
| 数据不更新 | 看 git log 是否 push 成功 |
| 收到法律投诉 | 立即下线（git revert 或 Vercel 关停） |
| 流量过大 | Vercel 免费额度 100GB/月，应该够 |

---

## 💰 成本

| 项 | 价格 |
|---|---|
| GitHub | 免费 |
| Vercel（个人） | 免费 |
| Google Analytics | 免费 |
| 自定义域名（可选） | ~70 元/年 |
| **总计** | **0-70 元/年** |

---

## 📞 需要帮助？

文件位置：`/Users/dongyuhan03/Desktop/crime-map-recife`

下一步建议：
1. 先本地跑通 → `serve public -p 3000`
2. 再部署 Vercel → 拿真实链接
3. 找 5-10 个朋友测试 → 收集反馈
4. 发到巴西本地 Reddit / Facebook 群推广

祝上线顺利 🚀
