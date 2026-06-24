#!/bin/bash
# 站外部署：GitHub → Vercel 自动触发
# 用法：bash scripts/deploy_external.sh
set -e
cd "$(dirname "$0")/.."

T0=$(date +%s)
echo "🌍 [$(date '+%H:%M:%S')] 开始站外部署 (GitHub → Vercel)"
echo ""

# ① 导最新 JSON
echo "📤 [1/2] 导出 JSON..."
python3 scripts/export_json.py
echo ""

# ② 推 GitHub 触发 Vercel
echo "🚀 [2/2] 推 GitHub..."
git add public/ 2>/dev/null || true

if git diff --cached --quiet; then
    echo "    ⚠️  public/ 没改动，跳过"
else
    git commit -m "data: auto-update LLM at $(date '+%Y-%m-%d %H:%M')" 2>&1 | tail -2
    git push origin main 2>&1 | tail -3
    echo ""
    echo "    ✅ 已推 GitHub，Vercel 将 1-2 分钟内自动部署"
fi

T1=$(date +%s)
echo ""
echo "✅ [$(date '+%H:%M:%S')] 完成！耗时 $((T1-T0)) 秒"
echo "🌐 站外域名：https://crime-map-recife-.vercel.app  (你 Vercel 主域名)"
