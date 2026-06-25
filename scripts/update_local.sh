#!/bin/bash
# 本地一键更新数据流水线
# 用法：bash scripts/update_local.sh
#
# 链路：拉 GHA 增量 → 合并到 DB → 跑 LLM（如有未跑的）→ 刷展示层 → 导出 JSON → 推线上

set -e
cd "$(dirname "$0")/.."

echo "===== 1. 拉 GHA 抓的最新 raw 数据 ====="
git pull origin main --no-rebase --no-edit 2>&1 | tail -3

echo ""
echo "===== 2. 激活 venv ====="
source .venv/bin/activate

echo ""
echo "===== 3. 合并 raw 到 DB（增量，去重） ====="
python scripts/merge_raw_to_db.py

echo ""
echo "===== 4. 跑 LLM（A/B/C 段） ====="
read -p "是否要跑 LLM？(需要 API key + 较长时间) [y/N] " yn
if [[ $yn == "y" || $yn == "Y" ]]; then
    if [ -f scripts/run_llm_pipeline.py ]; then
        python scripts/run_llm_pipeline.py
    else
        python scripts/llm_verify.py
    fi
fi

echo ""
echo "===== 5. 刷新展示层 ====="
python scripts/refresh_published.py

echo ""
echo "===== 6. 导出前端 JSON ====="
python scripts/export_from_published.py

echo ""
echo "===== 7. 推线上 ====="
git add public/rss_incidents.json public/rss_incidents_lite.json public/meta.json 2>/dev/null || true
git diff --staged --quiet && echo "无变化" || {
    COUNT=$(python -c "import json; print(len(json.load(open('public/rss_incidents.json'))))")
    LATEST=$(python -c "import json; d=json.load(open('public/rss_incidents.json')); ts=sorted([x.get('pub_date','') for x in d if x.get('pub_date')], reverse=True); print(ts[0] if ts else '?')")
    git commit -m "data: ${COUNT} incidents (latest ${LATEST})"
    git push origin main
}

echo ""
echo "✅ 完成！https://crime-map-recife.vercel.app/"
