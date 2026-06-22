#!/usr/bin/env python3
"""
🚀 端到端流水线：爬虫 → 落表 → 调 LLM → 回写 dwd
============================================================
一条命令打通全流程：
  python3 scripts/pipeline.py                    # 全流程
  python3 scripts/pipeline.py --skip-fetch       # 跳过爬虫
  python3 scripts/pipeline.py --skip-llm         # 跳过 LLM
  python3 scripts/pipeline.py --llm mock         # 用 mock LLM
  python3 scripts/pipeline.py --llm deepseek     # 用 DeepSeek（需 DEEPSEEK_API_KEY）
  python3 scripts/pipeline.py --llm openai       # 用 OpenAI（需 OPENAI_API_KEY）
  python3 scripts/pipeline.py --llm kwai         # 用快手内部网关（需 KWAI_LLM_URL + KWAI_LLM_TOKEN）

流程：
  Step 1: scripts/fetch_all.py        爬 50+ RSS → public/rss_incidents.json
  Step 2: scripts/build_sqlite.py     落 SQLite（ods + dwd 两张表）
  Step 3: scripts/llm_call.py         调 LLM → data/crime_llm_result.ndjson
  Step 4: scripts/db.py merge ...     回写 dwd 表
  Step 5: 最终质量报告
"""
import sys, os, subprocess, time, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def run(cmd, label):
    print(f'\n{"="*60}\n▶ {label}\n  $ {" ".join(cmd)}\n{"="*60}')
    t0 = time.time()
    r = subprocess.run(cmd, cwd=str(ROOT))
    dt = time.time() - t0
    if r.returncode != 0:
        print(f'❌ {label} 失败 (exit {r.returncode})'); sys.exit(1)
    print(f'✅ {label} 完成 ({dt:.1f}s)')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skip-fetch', action='store_true')
    ap.add_argument('--skip-llm', action='store_true')
    ap.add_argument('--llm', default='mock', choices=['mock','deepseek','openai','kwai'])
    ap.add_argument('--limit', type=int, default=0, help='LLM 处理多少条；0=全量')
    ap.add_argument('--only-default', action='store_true', help='LLM 只跑 default 兜底数据')
    args = ap.parse_args()

    print('🚀 巴西犯罪地图流水线')
    print(f'   爬虫:  {"跳过" if args.skip_fetch else "✓"}')
    print(f'   LLM:   {"跳过" if args.skip_llm else args.llm}')

    # ============== Step 1: 爬虫 ==============
    if not args.skip_fetch:
        run(['python3','scripts/fetch_all.py'], 'Step 1: 爬 RSS')
    else:
        print('\n⏭  跳过爬虫，使用现有 public/rss_incidents.json')

    # ============== Step 2: 落 SQLite ==============
    run(['python3','scripts/build_sqlite.py'], 'Step 2: 落 SQLite（ods + dwd）')

    # ============== Step 3: 调 LLM ==============
    if not args.skip_llm:
        if args.llm == 'mock':
            run(['python3','scripts/export_for_llm.py'], '  3a: 导出给 LLM 的 CSV')
            run(['python3','scripts/mock_llm.py'], '  3b: 模拟 LLM 跑校验')
        else:
            cmd = ['python3','scripts/llm_call.py','--provider',args.llm]
            if args.limit: cmd += ['--limit', str(args.limit)]
            if args.only_default: cmd.append('--only-default')
            run(cmd, f'Step 3: 调真实 LLM ({args.llm})')

        # ============== Step 4: 回写 dwd ==============
        run(['python3','scripts/db.py','merge','data/crime_llm_result.ndjson'],
            'Step 4: 回写 dwd 表')
    else:
        print('\n⏭  跳过 LLM')

    # ============== Step 5: 报告 ==============
    print(f'\n{"="*60}\n📊 最终数据质量报告\n{"="*60}')
    subprocess.run(['python3','scripts/db.py','status'], cwd=str(ROOT))

    print(f'\n🎉 流水线完成！')
    print(f'   数据库: data/crime_map.db')
    print(f'   查询:   python3 scripts/db.py')

if __name__=='__main__':
    main()
