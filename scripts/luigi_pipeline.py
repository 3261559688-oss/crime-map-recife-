#!/usr/bin/env python3
"""
🌊 Luigi 工作流：爬虫 → 落表 → LLM-A → LLM-B → LLM-C → 报告
============================================================
依赖图：
  FetchRSS
     ↓
  BuildSQLite
     ↓
  LLMStageA (is_crime)
     ↓
  LLMStageB (type)
     ↓
  LLMStageC (geo)
     ↓
  FinalReport

用法：
  # 跑全流程
  python3 scripts/luigi_pipeline.py FinalReport --local-scheduler

  # 跑到指定阶段
  python3 scripts/luigi_pipeline.py LLMStageA --local-scheduler

  # 强制重跑某阶段（删 output 文件即可）
  rm data/.luigi_done_stage_a && python3 scripts/luigi_pipeline.py LLMStageA --local-scheduler

  # 启动 web UI 看 DAG
  luigid &
  open http://localhost:8082
"""
import luigi
import subprocess
import sys
import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)

# 通用参数
class Config(luigi.Config):
    date  = luigi.Parameter(default=date.today().strftime('%Y%m%d'))
    llm_provider = luigi.Parameter(default='mock')   # mock/deepseek/openai/kwai
    limit = luigi.IntParameter(default=0)             # 0 = 全量

# ============================================================
# Task 1: 爬 RSS
# ============================================================
class FetchRSS(luigi.Task):
    date = luigi.Parameter(default=date.today().strftime('%Y%m%d'))

    def output(self):
        return luigi.LocalTarget(str(ROOT/'public/rss_incidents.json'))

    def run(self):
        print(f'📡 FetchRSS [{self.date}]')
        r = subprocess.run(['python3', str(ROOT/'scripts/fetch_all.py')], cwd=str(ROOT))
        if r.returncode != 0:
            raise Exception('fetch_all.py failed')

# ============================================================
# Task 2: 落 SQLite (ods + dwd)
# ============================================================
class BuildSQLite(luigi.Task):
    date = luigi.Parameter(default=date.today().strftime('%Y%m%d'))

    def requires(self):
        return FetchRSS(date=self.date)

    def output(self):
        return luigi.LocalTarget(str(DATA/'crime_map.db'))

    def run(self):
        print(f'📦 BuildSQLite [{self.date}]')
        r = subprocess.run(['python3', str(ROOT/'scripts/build_sqlite.py')], cwd=str(ROOT))
        if r.returncode != 0:
            raise Exception('build_sqlite.py failed')

# ============================================================
# Task 3A: LLM Stage A (is_crime)
# ============================================================
class LLMStageA(luigi.Task):
    date = luigi.Parameter(default=date.today().strftime('%Y%m%d'))
    provider = luigi.Parameter(default='mock')
    limit = luigi.IntParameter(default=0)

    def requires(self):
        return BuildSQLite(date=self.date)

    def output(self):
        return luigi.LocalTarget(str(DATA/f'.luigi_done_stage_a_{self.date}'))

    def run(self):
        print(f'🅰️  LLMStageA: is_crime [{self.provider}] limit={self.limit}')
        cmd = ['python3', str(ROOT/'scripts/llm_call_v2.py'),
               '--stage','a','--provider',self.provider]
        if self.limit: cmd += ['--limit', str(self.limit)]
        r = subprocess.run(cmd, cwd=str(ROOT))
        if r.returncode != 0:
            raise Exception('LLMStageA failed')
        Path(self.output().path).write_text(f'done {self.date}')

# ============================================================
# Task 3B: LLM Stage B (type)
# ============================================================
class LLMStageB(luigi.Task):
    date = luigi.Parameter(default=date.today().strftime('%Y%m%d'))
    provider = luigi.Parameter(default='mock')
    limit = luigi.IntParameter(default=0)

    def requires(self):
        return LLMStageA(date=self.date, provider=self.provider, limit=self.limit)

    def output(self):
        return luigi.LocalTarget(str(DATA/f'.luigi_done_stage_b_{self.date}'))

    def run(self):
        print(f'🅱️  LLMStageB: type [{self.provider}]')
        cmd = ['python3', str(ROOT/'scripts/llm_call_v2.py'),
               '--stage','b','--provider',self.provider]
        if self.limit: cmd += ['--limit', str(self.limit)]
        r = subprocess.run(cmd, cwd=str(ROOT))
        if r.returncode != 0:
            raise Exception('LLMStageB failed')
        Path(self.output().path).write_text(f'done {self.date}')

# ============================================================
# Task 3C: LLM Stage C (geo)
# ============================================================
class LLMStageC(luigi.Task):
    date = luigi.Parameter(default=date.today().strftime('%Y%m%d'))
    provider = luigi.Parameter(default='mock')
    limit = luigi.IntParameter(default=0)

    def requires(self):
        return LLMStageB(date=self.date, provider=self.provider, limit=self.limit)

    def output(self):
        return luigi.LocalTarget(str(DATA/f'.luigi_done_stage_c_{self.date}'))

    def run(self):
        print(f'🅲  LLMStageC: geo [{self.provider}]')
        cmd = ['python3', str(ROOT/'scripts/llm_call_v2.py'),
               '--stage','c','--provider',self.provider]
        if self.limit: cmd += ['--limit', str(self.limit)]
        r = subprocess.run(cmd, cwd=str(ROOT))
        if r.returncode != 0:
            raise Exception('LLMStageC failed')
        Path(self.output().path).write_text(f'done {self.date}')

# ============================================================
# Task 4: 最终报告
# ============================================================
class FinalReport(luigi.Task):
    date = luigi.Parameter(default=date.today().strftime('%Y%m%d'))
    provider = luigi.Parameter(default='mock')
    limit = luigi.IntParameter(default=0)

    def requires(self):
        return LLMStageC(date=self.date, provider=self.provider, limit=self.limit)

    def output(self):
        return luigi.LocalTarget(str(DATA/f'final_report_{self.date}.txt'))

    def run(self):
        print(f'📊 FinalReport [{self.date}]')
        import sqlite3
        conn = sqlite3.connect(str(DATA/'crime_map.db'))
        cur = conn.cursor()

        # 收集报告数据
        lines = [
            f'='*60,
            f'巴西犯罪地图 — 三段 LLM 校验报告',
            f'日期: {self.date}  LLM: {self.provider}',
            f'='*60,
            '',
            '【三段校验完成情况】',
        ]

        for stage, col in [('A','llm_a_is_crime'),('B','llm_b_type'),('C','llm_c_state')]:
            cur.execute(f'SELECT count(*) FROM dwd_intl_crime_incident_di WHERE {col} IS NOT NULL')
            n = cur.fetchone()[0]
            lines.append(f'  Stage {stage} ({col}): {n} 条已校验')

        lines.append('')
        lines.append('【Stage A 真伪分布】')
        cur.execute('SELECT llm_a_is_crime, count(*) FROM dwd_intl_crime_incident_di WHERE llm_a_is_crime IS NOT NULL GROUP BY llm_a_is_crime')
        for v,c in cur.fetchall():
            label = '真犯罪' if v==1 else '非犯罪'
            lines.append(f'  {label}: {c}')

        lines.append('')
        lines.append('【Stage B 类型 TOP 10】')
        cur.execute('SELECT llm_b_type, count(*) FROM dwd_intl_crime_incident_di WHERE llm_b_type IS NOT NULL GROUP BY llm_b_type ORDER BY 2 DESC LIMIT 10')
        for t,c in cur.fetchall():
            lines.append(f'  {t:12} {c}')

        lines.append('')
        lines.append('【Stage C 州分布 TOP 10】')
        cur.execute('SELECT llm_c_state, count(*) FROM dwd_intl_crime_incident_di WHERE llm_c_state IS NOT NULL GROUP BY llm_c_state ORDER BY 2 DESC LIMIT 10')
        for s,c in cur.fetchall():
            lines.append(f'  {s or "(空)":4} {c}')

        lines.append('')
        lines.append('【类型变更率（关键词 vs LLM）】')
        cur.execute('SELECT count(*) FROM dwd_intl_crime_incident_di WHERE llm_b_type IS NOT NULL AND llm_b_type != crime_type')
        changed = cur.fetchone()[0]
        cur.execute('SELECT count(*) FROM dwd_intl_crime_incident_di WHERE llm_b_type IS NOT NULL')
        total_b = cur.fetchone()[0]
        if total_b: lines.append(f'  LLM 改判: {changed}/{total_b} ({changed*100/total_b:.1f}%)')

        lines.append('')
        lines.append('【地理校正率（关键词 state vs LLM state）】')
        cur.execute('SELECT count(*) FROM dwd_intl_crime_incident_di WHERE llm_c_state IS NOT NULL AND llm_c_state != state')
        changed_c = cur.fetchone()[0]
        cur.execute('SELECT count(*) FROM dwd_intl_crime_incident_di WHERE llm_c_state IS NOT NULL')
        total_c = cur.fetchone()[0]
        if total_c: lines.append(f'  LLM 改判: {changed_c}/{total_c} ({changed_c*100/total_c:.1f}%)')

        report = '\n'.join(lines)
        print(report)
        Path(self.output().path).write_text(report)
        conn.close()

# ============================================================
# Main
# ============================================================
if __name__ == '__main__':
    luigi.run()
