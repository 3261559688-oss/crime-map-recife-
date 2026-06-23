#!/bin/bash
# Crime Map 一键部署到 frontend-cloud
# 用法: bash scripts/deploy.sh
set -e

cd "$(dirname "$0")/.."

echo "🚀 开始部署 → frontend-cloud"
echo "📂 目录: $(pwd)/public"
echo ""

# 1) 检查登录态
appwrite-cf whoami > /dev/null 2>&1 || {
    echo "⚠️  未登录，执行 appwrite-cf login-ks ..."
    appwrite-cf login-ks
}

# 2) 部署
npx -y @codeflicker/frontend-cloud-cli@latest deploy --dir public

echo ""
echo "✅ 部署完成！"
echo "🌐 https://crime-map-brasil.frontend-cloud.corp.kuaishou.com"
