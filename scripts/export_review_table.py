#!/usr/bin/env python3
"""导出"事件回溯表" — 4 列简洁版

输出:
  data/review/incidents_review.csv   (可用 Excel/Numbers 打开)
  data/review/incidents_review.xlsx  (Excel 原生格式，自动加超链接)
  data/review/incidents_review.md    (Markdown，可贴文档)
"""
import sqlite3, pandas as pd, os
from datetime import datetime

OUT_DIR = "data/review"
os.makedirs(OUT_DIR, exist_ok=True)

con = sqlite3.connect("data/crime_map.db")
df = pd.read_sql("""
    SELECT
        title AS 事件标题,
        COALESCE(pub_date, '') AS 时间,
        (state || ' / ' || city || COALESCE(' / ' || neighborhood, '')) AS 城市,
        link AS 链接,
        type AS 罪种,
        llm_b_score AS 置信度
    FROM incidents_published
    ORDER BY pub_ts DESC NULLS LAST
""", con)
con.close()

# 1. CSV — 通用，Excel 双击就开
df.to_csv(f"{OUT_DIR}/incidents_review.csv", index=False, encoding='utf-8-sig')  # utf-8-sig 让 Excel 正确显示中文

# 2. xlsx — 自动加超链接 + 列宽
with pd.ExcelWriter(f"{OUT_DIR}/incidents_review.xlsx", engine='openpyxl') as w:
    df.to_excel(w, sheet_name='事件回溯表', index=False)
    ws = w.sheets['事件回溯表']
    # 自动列宽
    for col_idx, col in enumerate(df.columns, 1):
        max_len = max(df[col].astype(str).map(len).max(), len(col))
        ws.column_dimensions[chr(64 + col_idx)].width = min(max_len + 2, 60)
    # 链接列改超链接
    from openpyxl.styles import Font
    link_col = list(df.columns).index('链接') + 1
    blue = Font(color='0000FF', underline='single')
    for row_idx in range(2, len(df) + 2):
        cell = ws.cell(row=row_idx, column=link_col)
        if cell.value:
            cell.hyperlink = cell.value
            cell.font = blue
    # 冻结表头
    ws.freeze_panes = 'A2'

# 3. Markdown — 取前 50 条，便于贴文档/IM
md_path = f"{OUT_DIR}/incidents_review.md"
with open(md_path, 'w', encoding='utf-8') as f:
    f.write(f"# 巴西犯罪事件回溯表（最近 50 条）\n\n")
    f.write(f"生成时间: {datetime.now():%Y-%m-%d %H:%M}\n")
    f.write(f"共 {len(df)} 条记录\n\n")
    f.write("| # | 时间 | 城市 | 罪种 | 标题 | 链接 |\n")
    f.write("|---|---|---|---|---|---|\n")
    for i, r in df.head(50).iterrows():
        title = str(r['事件标题'])[:60].replace('|', '\\|')
        f.write(f"| {i+1} | {r['时间'][:10]} | {r['城市']} | {r['罪种']} | {title} | [打开]({r['链接']}) |\n")

print(f"✅ CSV  → {OUT_DIR}/incidents_review.csv      ({len(df)} 条)")
print(f"✅ XLSX → {OUT_DIR}/incidents_review.xlsx     ({len(df)} 条，含超链接)")
print(f"✅ MD   → {OUT_DIR}/incidents_review.md       (前 50 条预览)")
print()
print("【前 5 条样本】")
print(df.head(5).to_string(index=False, max_colwidth=40))
