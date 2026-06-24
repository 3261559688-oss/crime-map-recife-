#!/bin/bash
# 双部署：站内 frontend-cloud + 站外 GitHub→Vercel
# 用法：bash scripts/deploy_dual.sh
set -e
cd "$(dirname "$0")/.."

T0=$(date +%s)
echo "🚀 [$(date '+%H:%M:%S')] 开始双部署"
echo ""

# ───────────────────────────────────────
# 1) 导最新 JSON
# ───────────────────────────────────────
echo "📤 [1/3] 导出 JSON..."
python3 scripts/export_json.py
echo ""

# ───────────────────────────────────────
# 2) 站内：frontend-cloud（公司内网）
# ───────────────────────────────────────
echo "☁️  [2/3] 部署站内 frontend-cloud..."
npx -y @codeflicker/frontend-cloud-cli@latest deploy --dir public 2>&1 | tail -5
echo ""
echo "    ✅ https://crime-map-brasil.frontend-cloud.corp.kuaishou.com"
echo ""

# ───────────────────────────────────────
# 3) 站外：GitHub → 触发 Vercel 自动部署
# ───────────────────────────────────────
echo "🌍 [3/3] 推 GitHub 触发 Vercel 站外部署..."

# 提交数据更新到一个临时分支（避免污染 main 历史）
git add public/rss_incidents.json public/api/incidents.json public/api/incidents.ndjson public/index.html 2>/dev/null || true

if git diff --cached --quiet; then
    echo "    ⚠️  没有 public/ 改动，跳过 GitHub 推送"
else
    git commit -m "data: auto-update LLM data $(date '+%Y-%m-%d %H:%M')" 2>&1 | tail -2
    git push origin main 2>&1 | tail -3
    echo ""
    echo "    ✅ 已推到 GitHub，Vercel 将自动部署（~2 分钟生效）"
    echo "    🔗 你的 Vercel 域名（之前部署过的那个）会自动刷新"
fi

T1=$(date +%s)
echo ""
echo "════════════════════════════════════════════"
echo "✅ [$(date '+%H:%M:%S')] 双部署完成！耗时 $((T1-T0)) 秒"
echo "════════════════════════════════════════════"
echo ""
echo "🌐 访问地址："
echo "   站内：https://crime-map-brasil.frontend-cloud.corp.kuaishou.com"
echo "   站外：https://crime-map-recife-.vercel.app  (或你 Vercel 自定义域名)"
