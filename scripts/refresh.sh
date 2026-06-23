#!/bin/bash
# Crime Map 一键刷新：拉新数据 + LLM + 导 JSON + 部署
# 用法：bash scripts/refresh.sh
set -e
cd "$(dirname "$0")/.."

T0=$(date +%s)
echo "🚀 [$(date '+%H:%M:%S')] 开始刷新流水线"

# 加载环境变量
[ -f .env ] && set -a && source .env && set +a

# ① 拉 RSS（约 30 秒）
echo ""
echo "📡 [1/5] 拉 RSS 67 源..."
python3 scripts/fetch_all.py 2>&1 | tail -3

# ② 入库（增量 INSERT OR IGNORE）
echo ""
echo "💾 [2/5] 入库 SQLite..."
python3 scripts/build_sqlite.py --append 2>&1 | tail -3

# ③④⑤ LLM 三段（仅跑新增 NULL 字段）
if [ -n "$WQ_API_KEY" ]; then
    echo ""
    echo "🧠 [3/5] LLM A (真伪)..."
    python3 scripts/llm_call_v2.py --stage a --provider wanqing --workers 4 --batch 500 2>&1 | tail -3
    echo ""
    echo "🧠 [4/5] LLM B (类型)..."
    python3 scripts/llm_call_v2.py --stage b --provider wanqing --workers 4 --batch 500 2>&1 | tail -3
    echo ""
    echo "🧠 [5/5] LLM C (地理)..."
    python3 scripts/llm_call_v2.py --stage c --provider wanqing --workers 4 --batch 500 2>&1 | tail -3
else
    echo "⚠️  WQ_API_KEY 未设置，跳过 LLM"
fi

# 导 JSON
echo ""
echo "📤 导出 JSON..."
python3 scripts/export_json.py

# 备份 SQLite 到云端（顺便部署上去做异地容灾）
echo ""
echo "💾 备份 SQLite 到 public/backup/..."
mkdir -p public/backup
TS=$(date +%Y%m%d_%H%M)
gzip -kf data/crime_map.db
mv data/crime_map.db.gz "public/backup/crime_map_${TS}.db.gz"
# 同时维护一份"latest"用于一键拉取
cp "public/backup/crime_map_${TS}.db.gz" public/backup/crime_map_latest.db.gz
# 只保留最近 10 个备份（节省云端空间）
ls -t public/backup/crime_map_2*.db.gz 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null || true
echo "  ✅ $(ls public/backup/crime_map_2*.db.gz | wc -l | tr -d ' ') 份备份在 public/backup/"

# 部署
echo ""
echo "☁️  部署 frontend-cloud..."
npx -y @codeflicker/frontend-cloud-cli@latest deploy --dir public 2>&1 | tail -5

T1=$(date +%s)
echo ""
echo "✅ [$(date '+%H:%M:%S')] 完成！耗时 $((T1-T0)) 秒"
echo "🌐 https://crime-map-brasil.frontend-cloud.corp.kuaishou.com"
