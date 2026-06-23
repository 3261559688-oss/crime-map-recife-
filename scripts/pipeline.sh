#!/bin/bash
# Crime Map 主流水线
# 1) 拉 RSS  2) 入库  3) LLM 三段  4) 导前端 JSON  5) 通知 API 热更新
set -e
cd "$(dirname "$0")/.."

LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"
echo "$LOG_PREFIX ===== pipeline 开始 ====="

# ① 拉 RSS（约 30s）
echo "$LOG_PREFIX [1/5] 拉 RSS..."
python3 scripts/fetch_all.py || { echo "$LOG_PREFIX ❌ fetch 失败"; exit 1; }

# ② 入库（INSERT OR IGNORE，不洗 LLM 结果）
echo "$LOG_PREFIX [2/5] 入库..."
python3 scripts/build_sqlite.py --append || { echo "$LOG_PREFIX ❌ build_sqlite 失败"; exit 1; }

# ③④⑤ LLM 三段（只跑 NULL 字段，增量）
if [ -n "$WQ_API_KEY" ]; then
    echo "$LOG_PREFIX [3/5] LLM A 真伪..."
    python3 scripts/llm_call_v2.py --stage a --provider wanqing --workers 4 --batch 100 || true
    echo "$LOG_PREFIX [4/5] LLM B 类型..."
    python3 scripts/llm_call_v2.py --stage b --provider wanqing --workers 4 --batch 100 || true
    echo "$LOG_PREFIX [5/5] LLM C 地理..."
    python3 scripts/llm_call_v2.py --stage c --provider wanqing --workers 4 --batch 100 || true
else
    echo "$LOG_PREFIX ⚠️  WQ_API_KEY 未配置，跳过 LLM"
fi

# ⑥ 通知 API 重新加载内存（如果在跑）
echo "$LOG_PREFIX 热更新 API..."
curl -sf http://localhost:8787/api/reload > /dev/null 2>&1 || echo "$LOG_PREFIX (API 未在跑，跳过热更新)"

echo "$LOG_PREFIX ===== pipeline 完成 ====="
