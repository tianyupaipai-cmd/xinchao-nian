# ============================================================
# Ombre Brain（心潮念 vendored 版）Docker 构建
#   基于 P0luz/Ombre-Brain（原, MIT）→ CyberSealNull 二改（非商业）→ 心潮念加 breath-meta。
#   许可证见 LICENSE.P0luz-MIT / LICENSE.CyberSealNull / ../NOTICE / MODIFICATIONS.md。
#
#   构建： docker compose up -d --build   （由上层 compose.yaml 驱动）
#   跳过 cloudflared： docker build --build-arg INSTALL_CLOUDFLARED=0 .
# ============================================================

FROM python:3.12-slim

WORKDIR /app

# cloudflared（Dashboard 的 Tunnel 一键管理，可选）。用镜像自带 python 从 GitHub Releases
# 下载，不装 curl、不跑 apt-get update，避开 Debian 源间歇性 502。不需要可传 =0 跳过。
ARG INSTALL_CLOUDFLARED=1
COPY deploy/fetch_cloudflared.py /tmp/fetch_cloudflared.py
RUN set -eu; \
    if [ "$INSTALL_CLOUDFLARED" = "1" ]; then \
        python /tmp/fetch_cloudflared.py /usr/local/bin/cloudflared; \
        chmod +x /usr/local/bin/cloudflared; \
    else \
        echo "[build] INSTALL_CLOUDFLARED=0 → 跳过 cloudflared"; \
    fi; \
    rm -f /tmp/fetch_cloudflared.py

# 先装依赖（利用 Docker 缓存）。受限网络可传 PIP_INDEX_URL/PIP_TRUSTED_HOST。
ARG PIP_INDEX_URL=""
ARG PIP_TRUSTED_HOST=""
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir --retries 10 --timeout 120 \
        ${PIP_INDEX_URL:+-i "$PIP_INDEX_URL"} \
        ${PIP_TRUSTED_HOST:+--trusted-host "$PIP_TRUSTED_HOST"} \
        --require-hashes -r requirements.lock.txt

# 项目文件
COPY src/ ./src/
COPY frontend/ ./frontend/
COPY VERSION ./VERSION
COPY config.default.yaml ./config.default.yaml
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# 面向用户/模型的说明文档（本版本实际存在的几篇）
COPY docs/CLAUDE_PROMPT.md docs/INTERNALS.md docs/MULTI_OWNER.md docs/OPERATIONS.md ./docs/
COPY README.upstream.md ./README.md
COPY CHANGELOG.md ./CHANGELOG.md

VOLUME ["/app/buckets"]

ENV OMBRE_TRANSPORT=streamable-http
ENV OMBRE_PORT=8000
ENV OMBRE_BUCKETS_DIR=/app/buckets
ENV OMBRE_CONFIG_PATH=/app/buckets/config.yaml
ENV OMBRE_EMBED_BACKEND=api

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
