#!/usr/bin/env python3
"""
本地 SQLite 查询 / 管理 CLI
============================================================
用法:
  python3 scripts/db.py                  交互式
  python3 scripts/db.py status           表状态
  python3 scripts/db.py q "<SQL>"        执行 SQL
  python3 scripts/db.py rebuild          从 json 重建
  python3 scripts/db.py merge <file>     合并 LLM 结果
"""
import sys
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data' / 'crime_map.db'

def get_conn():
    if not DB.exists():
        print(f'❌ 数据库不存在：{DB}\n   请先跑：python3 scripts/build_sqlite.py')
        sys.exit(1)
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn

def cmd_status():
    """显示数据库状态"""
    conn = get_conn(); cur = conn.cursor()
    print(f'📁 数据库: {DB} ({DB.stat().st_size/1024/1024:.2f} MB)\n')

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f'📊 表 ({len(tables)}):')
    for t in tables:
        cur.execute(f'SELECT count(*) FROM {t}')
        print(f'  - {t:35} {cur.fetchone()[0]:>8,} 条')

    cur.execute("SELECT name FROM sqlite_master WHERE type='view'")
    views = [r[0] for r in cur.fetchall()]
    print(f'\n👁️  视图 ({len(views)}):')
    for v in views: print(f'  - {v}')

    print('\n📋 v_data_quality:')
    cur.execute('SELECT * FROM v_data_quality')
    cols = [d[0] for d in cur.description]
    for row in cur.fetchall():
        for k,v in zip(cols, row): print(f'    {k:18} = {v}')

def cmd_query(sql):
    """执行 SQL"""
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(sql)
    except Exception as e:
        print(f'❌ {e}'); return
    if cur.description:
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        widths = [max(len(c), *(len(str(r[i] or '')) for r in rows[:50])) for i,c in enumerate(cols)]
        widths = [min(w, 40) for w in widths]
        print(' | '.join(c.ljust(widths[i]) for i,c in enumerate(cols)))
        print('-+-'.join('-'*w for w in widths))
        for r in rows[:100]:
            print(' | '.join(str(r[i] or '')[:40].ljust(widths[i]) for i in range(len(cols))))
        if len(rows) > 100:
            print(f'... 共 {len(rows)} 行，仅显示前 100 行')
    else:
        conn.commit()
        print(f'✅ 影响 {cur.rowcount} 行')

def cmd_interactive():
    """交互模式"""
    print(f'🟢 SQLite 交互模式 | {DB}\n输入 SQL（多行用 ; 结尾），输入 .quit 退出，.tables 看表\n')
    conn = get_conn()
    buf = []
    while True:
        try:
            line = input('sql> ' if not buf else ' ... ')
        except (EOFError, KeyboardInterrupt):
            break
        if line.strip() in ('.quit', '.exit', 'quit', 'exit'): break
        if line.strip() == '.tables':
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
            for r in cur.fetchall(): print(f'  - {r[0]}')
            continue
        if line.strip() == '.help':
            print('  .tables  列出表/视图\n  .quit    退出\n  其他: 输入 SQL，以 ; 结尾执行')
            continue
        buf.append(line)
        if line.rstrip().endswith(';'):
            sql = '\n'.join(buf); buf = []
            cmd_query(sql.rstrip(';'))

def cmd_merge(ndjson_path):
    """合并 LLM NDJSON 结果到 dwd 表"""
    p = Path(ndjson_path)
    if not p.exists(): print(f'❌ 文件不存在：{p}'); return
    conn = get_conn(); cur = conn.cursor()
    ok=0; fail=0
    with open(p) as f:
        for ln in f:
            ln = ln.strip()
            if not ln: continue
            try:
                r = json.loads(ln)
                cur.execute("""
                  UPDATE dwd_intl_crime_incident_di SET
                    llm_verified=?, llm_score=?, llm_state=?, llm_city=?,
                    llm_neighbor=?, llm_type=?, llm_reason=?,
                    llm_at=datetime('now'), llm_model=?
                  WHERE event_id=?
                """, (
                    1 if r.get('llm_is_crime') else 0,
                    r.get('llm_score'),
                    r.get('llm_state'), r.get('llm_city'),
                    r.get('llm_neighbor'), r.get('llm_type'),
                    r.get('llm_reason'),
                    r.get('llm_model','manual'),
                    r.get('id'),
                ))
                if cur.rowcount > 0: ok += 1
                else: fail += 1
            except Exception as e:
                fail += 1
                print(f'  ⚠️ {e}: {ln[:60]}')
    conn.commit()
    print(f'✅ 合并完成: {ok} 条成功 / {fail} 条失败/未匹配')
    cur.execute("SELECT count(*) FROM dwd_intl_crime_incident_di WHERE llm_verified IS NOT NULL")
    print(f'   dwd 表 llm_verified 已填: {cur.fetchone()[0]:,}')

def main():
    if len(sys.argv) < 2:
        cmd_interactive(); return
    sub = sys.argv[1]
    if sub == 'status':       cmd_status()
    elif sub == 'q':          cmd_query(' '.join(sys.argv[2:]))
    elif sub == 'rebuild':
        import subprocess; subprocess.run(['python3', str(ROOT/'scripts/build_sqlite.py')])
    elif sub == 'merge':      cmd_merge(sys.argv[2])
    else:
        print(__doc__)

if __name__=='__main__':
    main()
