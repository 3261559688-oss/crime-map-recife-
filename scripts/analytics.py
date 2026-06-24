#!/usr/bin/env python3
"""
🦆 DuckDB 数据分析 — 一键跑 5 个开箱即用分析

用法:
  source .venv/bin/activate
  python scripts/analytics.py            # 跑全部
  python scripts/analytics.py 1          # 只跑第 1 个
  python scripts/analytics.py shell      # 进 DuckDB 交互模式

DuckDB 文件路径: data/parquet/*.parquet
原始 SQLite:    data/crime_map.db

⭐ 核心知识：
  - DuckDB 可以直接 SELECT * FROM 'xxx.parquet'，不用导入
  - 也可以 ATTACH 'xxx.db' (sqlite_scanner) 直接查 SQLite
  - SQL 语法跟 PostgreSQL 99% 一样
"""
import sys
import duckdb
import os

PARQ_PUB = "data/parquet/published_incidents.parquet"
PARQ_RAW = "data/parquet/raw_incidents.parquet"


def banner(n, title):
    print(f"\n{'═'*60}\n  分析 {n}: {title}\n{'═'*60}")


def a1_type_distribution(con):
    banner(1, "罪种分布 + 平均置信度 (LLM 觉得自己有多准)")
    print(con.sql(f"""
        SELECT
            type AS 罪种,
            COUNT(*) AS 条数,
            ROUND(AVG(llm_b_score), 1) AS 平均B置信度,
            ROUND(AVG(llm_c_score), 1) AS 平均C置信度,
            SUM(CASE WHEN neighborhood IS NOT NULL THEN 1 ELSE 0 END) AS 含街区数
        FROM '{PARQ_PUB}'
        GROUP BY type
        ORDER BY 条数 DESC
    """))


def a2_city_topn(con):
    banner(2, "城市犯罪热力榜 TOP 20")
    print(con.sql(f"""
        SELECT
            state AS 州, city AS 市,
            COUNT(*) AS 总数,
            SUM(CASE WHEN type='homicidio' THEN 1 ELSE 0 END) AS 杀人,
            SUM(CASE WHEN type='roubo' THEN 1 ELSE 0 END) AS 抢劫,
            SUM(CASE WHEN type='trafico' THEN 1 ELSE 0 END) AS 毒品,
            SUM(CASE WHEN type='sequestro' THEN 1 ELSE 0 END) AS 绑架,
            ROUND(100.0*SUM(CASE WHEN type='homicidio' THEN 1 ELSE 0 END)/COUNT(*),1) AS 杀人占比
        FROM '{PARQ_PUB}'
        GROUP BY state, city
        ORDER BY 总数 DESC
        LIMIT 20
    """))


def a3_state_homicide_ratio(con):
    banner(3, "各州谋杀占比（看哪个州最危险）")
    print(con.sql(f"""
        SELECT
            state AS 州,
            COUNT(*) AS 总事件,
            SUM(CASE WHEN type='homicidio' THEN 1 ELSE 0 END) AS 杀人案,
            ROUND(100.0 * SUM(CASE WHEN type='homicidio' THEN 1 ELSE 0 END) / COUNT(*), 1) AS 杀人占比
        FROM '{PARQ_PUB}'
        GROUP BY state
        HAVING COUNT(*) >= 20
        ORDER BY 杀人占比 DESC
        LIMIT 15
    """))


def a4_llm_filter_funnel(con):
    banner(4, "LLM 过滤漏斗（原始 → 展示）")
    print(con.sql(f"""
        WITH raw AS (
            SELECT COUNT(*) AS 抓取总数,
                   SUM(CASE WHEN llm_a_is_crime IS NOT NULL THEN 1 ELSE 0 END) AS A段已判,
                   SUM(CASE WHEN llm_a_is_crime = 1 THEN 1 ELSE 0 END) AS A段判真,
                   SUM(CASE WHEN llm_b_score IS NOT NULL THEN 1 ELSE 0 END) AS B段已判,
                   SUM(CASE WHEN llm_c_score IS NOT NULL THEN 1 ELSE 0 END) AS C段已判
            FROM '{PARQ_RAW}'
        ),
        pub AS (
            SELECT COUNT(*) AS 展示总数,
                   SUM(CASE WHEN neighborhood IS NOT NULL THEN 1 ELSE 0 END) AS 含街区
            FROM '{PARQ_PUB}'
        )
        SELECT * FROM raw, pub
    """))


def a5_lowconf_samples(con):
    banner(5, "低置信度样本 — 可能错判的（人工 Review 用）")
    print(con.sql(f"""
        SELECT
            type, city, llm_b_score, llm_c_score,
            SUBSTR(title, 1, 70) AS 标题
        FROM '{PARQ_PUB}'
        WHERE llm_b_score < 80
        ORDER BY llm_b_score ASC
        LIMIT 10
    """))


def shell(con):
    print("""
🦆 DuckDB 交互模式
   - 已自动注册 raw / pub 两张视图
   - 输入 SQL 直接查询，q / quit 退出
   - 示例：SELECT type, COUNT(*) FROM pub GROUP BY type LIMIT 5;
""")
    con.execute(f"CREATE VIEW raw AS SELECT * FROM '{PARQ_RAW}'")
    con.execute(f"CREATE VIEW pub AS SELECT * FROM '{PARQ_PUB}'")
    while True:
        try:
            q = input("duckdb> ").strip()
            if q.lower() in ("q", "quit", "exit", ""):
                break
            print(con.sql(q))
        except KeyboardInterrupt:
            print()
            break
        except Exception as e:
            print(f"❌ {e}")


def main():
    if not os.path.exists(PARQ_PUB):
        print(f"❌ {PARQ_PUB} 不存在，请先跑 scripts/sync_sqlite_to_parquet.py")
        sys.exit(1)

    con = duckdb.connect(database=':memory:')

    if len(sys.argv) > 1 and sys.argv[1] == 'shell':
        shell(con)
        return

    targets = [a1_type_distribution, a2_city_topn, a3_state_homicide_ratio,
               a4_llm_filter_funnel, a5_lowconf_samples]

    if len(sys.argv) > 1:
        idx = int(sys.argv[1]) - 1
        targets[idx](con)
    else:
        for fn in targets:
            fn(con)


if __name__ == "__main__":
    main()
