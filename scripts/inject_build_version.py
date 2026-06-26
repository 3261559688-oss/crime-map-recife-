#!/usr/bin/env python3
"""
发布前注入构建版本号：
  1. 用 git short sha + 时间戳生成 build_id
  2. 替换 public/index.html 中的 __BUILD_ID__ 占位符
  3. 写 public/version.json 给前端轮询
"""
import subprocess, time, json, os, re, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = ROOT / 'public' / 'index.html'
VERSION_JSON = ROOT / 'public' / 'version.json'

try:
    sha = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT).decode().strip()
except Exception:
    sha = 'unknown'

ts = int(time.time())
build_id = f'{sha}-{ts}'

# 1. 替换 HTML 占位符
html = HTML.read_text(encoding='utf-8')
# 把所有 '__BUILD_ID__'（包括之前的 build id）替换为新 build_id
new_html = re.sub(
    r"const __APP_BUILD__ = '[^']*';",
    f"const __APP_BUILD__ = '{build_id}';",
    html
)
HTML.write_text(new_html, encoding='utf-8')

# 2. 写 version.json
VERSION_JSON.write_text(json.dumps({
    'build': build_id,
    'sha': sha,
    'ts': ts,
}, indent=2), encoding='utf-8')

print(f'✅ build_id = {build_id}')
print(f'   public/index.html 已注入')
print(f'   public/version.json 已写入')
