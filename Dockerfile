# 站内部署用 Docker 镜像
# 同时跑：① 前端静态资源服务  ② API 后端  ③ cron 定时巡检
FROM python:3.10-slim

WORKDIR /app

# 系统依赖（cron + curl 用于健康检查）
RUN apt-get update && apt-get install -y --no-install-recommends \
    cron curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime

# Python 依赖（项目目前只用标准库 + openpyxl，超精简）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝代码
COPY scripts/ ./scripts/
COPY public/ ./public/

# 数据卷（SQLite 持久化）
VOLUME ["/app/data"]

# 配置 crontab
COPY scripts/crontab.txt /etc/cron.d/crime-map
RUN chmod 0644 /etc/cron.d/crime-map && crontab /etc/cron.d/crime-map

# 暴露端口
EXPOSE 8787

# 启动脚本
COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]
