#!/bin/bash
# Crime Map 容器入口
# 同时启动：① cron 守护进程  ② API 服务（前台跑）
set -e

echo "🚀 Crime Map 启动 — $(date)"
echo "Working dir: $(pwd)"

# 检查环境变量
if [ -z "$WQ_API_KEY" ]; then
    echo "⚠️  WQ_API_KEY 未设置，LLM 调用会失败"
fi

# 数据目录
mkdir -p /app/data
mkdir -p /app/public/api

# 首次冷启动：如果 SQLite 不存在，先跑一遍流水线
if [ ! -f /app/data/crime_map.db ]; then
    echo "❄️  冷启动：首次运行 pipeline"
    bash /app/scripts/pipeline.sh || echo "⚠️  pipeline 失败，但继续启动 API"
fi

# 启动 cron 守护
service cron start
echo "✅ cron 已启动（每 30 分钟巡检一次）"

# 前台启动 API（容器主进程）
echo "✅ 启动 API 服务 :8787"
exec python3 /app/scripts/api_server.py --port 8787 --host 0.0.0.0 --db /app/data/crime_map.db
