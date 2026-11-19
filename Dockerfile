FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 10001 metrics \
    && useradd --uid 10001 --gid metrics --no-create-home metrics \
    && mkdir /data && chown metrics:metrics /data && chmod 0770 /data
COPY scripts/collect.py scripts/normalize.py scripts/make_sample.py scripts/snapshot.py scripts/server.py scripts/worker.py ./scripts/
COPY web/build.py ./web/
COPY web/src/ ./web/src/
RUN mkdir -p data/sample \
    && python scripts/make_sample.py \
    && python web/build.py
USER 10001:10001

FROM base AS collector
USER root
ARG PYTHON_PACKAGE_INDEX=https://pypi.org/simple
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url "$PYTHON_PACKAGE_INDEX" -r requirements.txt
USER 10001:10001
CMD ["python", "scripts/worker.py"]

FROM base AS web
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).read()"]
CMD ["python", "scripts/server.py"]
