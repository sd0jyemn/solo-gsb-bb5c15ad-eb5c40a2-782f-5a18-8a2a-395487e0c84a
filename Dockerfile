FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    SOA_AUDIT_DB=/data/soa_audit.db

WORKDIR /app

# 先装依赖，利用构建缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests

# 构建期跑测试，避免坏镜像上线
RUN python -m pytest -q

# 非 root 用户运行，数据库目录对其可写
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app
USER appuser

VOLUME ["/data"]
EXPOSE 8000

# 启动即完成数据库初始化（应用 lifespan 内自动建表）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
