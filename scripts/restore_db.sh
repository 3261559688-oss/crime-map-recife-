#!/bin/bash
# Crime Map 从云端恢复 SQLite 到本机
# 用法：bash scripts/restore_db.sh
set -e
cd "$(dirname "$0")/.."

URL="https://crime-map-brasil.frontend-cloud.corp.kuaishou.com/backup/crime_map_latest.db.gz"
TARGET="data/crime_map.db"

echo "📥 从云端拉最新 SQLite 备份..."
echo "   $URL"

mkdir -p data

# 备份当前的 db（如果有）
if [ -f "$TARGET" ]; then
    BAK="${TARGET}.bak.$(date +%Y%m%d_%H%M%S)"
    cp "$TARGET" "$BAK"
    echo "   旧库已备份到: $BAK"
fi

# 下载并解压
curl -sfL "$URL" -o "${TARGET}.gz"
gunzip -f "${TARGET}.gz"

# 验证
ROWS=$(sqlite3 "$TARGET" "SELECT count(*) FROM dwd_intl_crime_incident_di" 2>/dev/null || echo "?")
SIZE=$(ls -lh "$TARGET" | awk '{print $5}')

echo ""
echo "✅ 恢复完成"
echo "   文件: $TARGET ($SIZE)"
echo "   条数: $ROWS"
