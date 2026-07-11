#!/bin/bash
# LLM Watchdog: 如果 LLM 进程卡住超过 5min 不前进，自动 kill 重启
set -e
cd /Users/dongyuhan03/Desktop/crime-map-recife
source .venv/bin/activate

get_progress(){
  python3 -c "
import sqlite3
con = sqlite3.connect('data/crime_map.db')
b = con.execute('SELECT COUNT(*) FROM dwd_intl_crime_incident_di WHERE llm_b_score IS NOT NULL').fetchone()[0]
c = con.execute('SELECT COUNT(*) FROM dwd_intl_crime_incident_di WHERE llm_c_score IS NOT NULL').fetchone()[0]
print(f'{b}-{c}')
"
}

run_once(){
  local stage=$1
  local label=$2
  echo "===== [$label] $(date) ====="
  local last_p=$(get_progress)
  local stall=0
  # 启动子进程
  python -u scripts/llm_call_v2.py --stage $stage --provider wanqing --limit 0 --workers 5 --throttle 0.2 &
  local pid=$!
  while kill -0 $pid 2>/dev/null; do
    sleep 90
    local cur=$(get_progress)
    if [ "$cur" = "$last_p" ]; then
      stall=$((stall+90))
      echo "[stall] $stall s without progress (B-C=$cur)"
      if [ $stall -ge 240 ]; then
        echo "[restart] killing $pid and restarting"
        kill -9 $pid 2>/dev/null || true
        pkill -9 -f "stage $stage" || true
        sleep 3
        return 1
      fi
    else
      stall=0
      last_p=$cur
      echo "[ok] progress $cur"
    fi
  done
  return 0
}

# B 段：最多重试 8 次
for i in $(seq 1 8); do
  python3 -c "
import sqlite3
con = sqlite3.connect('data/crime_map.db')
total = con.execute('SELECT COUNT(*) FROM dwd_intl_crime_incident_di WHERE llm_a_is_crime=1 AND llm_b_score IS NULL').fetchone()[0]
import sys; sys.exit(0 if total > 0 else 1)
" || { echo "[B done] no pending"; break; }
  echo "[try $i] starting B"
  run_once b B || echo "[try $i] B restarted"
done

# C 段
for i in $(seq 1 12); do
  python3 -c "
import sqlite3
con = sqlite3.connect('data/crime_map.db')
total = con.execute('SELECT COUNT(*) FROM dwd_intl_crime_incident_di WHERE llm_a_is_crime=1 AND llm_c_score IS NULL').fetchone()[0]
import sys; sys.exit(0 if total > 0 else 1)
" || { echo "[C done] no pending"; break; }
  echo "[try $i] starting C"
  run_once c C || echo "[try $i] C restarted"
done

# 收尾
echo "===== 收尾 $(date) ====="
python scripts/refresh_published.py
python scripts/export_from_published.py
python scripts/inject_build_version.py
git add public/rss_incidents.json public/rss_incidents_lite.json public/version.json public/index.html
git commit -m "data: LLM B+C 全跑完（watchdog）" || echo "no change"
git push origin main || true
echo "===== ALL DONE $(date) ====="
