# ============================================================
# 多阶段构建 — 极致压缩版
#
# 体积从 ~700MB → ~280MB,主要靠:
#   1) builder 阶段清掉 tests / docs / __pycache__ / RECORD
#   2) pip install --no-compile(不写 .pyc,运行时按需生成)
#   3) runtime 阶段只装 libpq5 + curl(去掉 libgl/libglib2,web 服务用不上)
#   4) 去掉 default-libmysqlclient-dev(本项目只用 PG)
#   5) 不复制 /usr/local/bin(改用 python -m uvicorn / python -m celery 启动)
#   6) 只 COPY 必要的 .py 文件,排除 .pyc / 静态资源 / 测试
# ============================================================

ARG DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian/
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security/
ARG PYPI_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple

# ---------- Stage 1: builder ----------
FROM python:3.12-slim-bookworm AS builder
ARG DEBIAN_MIRROR
ARG DEBIAN_SECURITY_MIRROR
ARG PYPI_INDEX_URL

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 编译期系统依赖(精简版):只装编译 psycopg + uvicorn[standard] 需要的
#   - libpq-dev:psycopg 编译
#   - 不用 libgl/libglib2(纯 web 服务用不上 GUI 库)
#   - 不用 default-libmysqlclient-dev(项目只用 PG)
RUN rm -f /etc/apt/sources.list \
        /etc/apt/sources.list.d/*.list \
        /etc/apt/sources.list.d/*.sources && \
    cat > /etc/apt/sources.list <<EOF
deb ${DEBIAN_MIRROR} bookworm main contrib non-free non-free-firmware
deb ${DEBIAN_MIRROR} bookworm-updates main contrib non-free non-free-firmware
deb ${DEBIAN_SECURITY_MIRROR} bookworm-security main contrib non-free non-free-firmware
EOF
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential pkg-config libpq-dev \
        && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# pip 走清华源
RUN pip config set global.index-url "${PYPI_INDEX_URL}" && \
    pip config set global.trusted-host "$(echo ${PYPI_INDEX_URL} | awk -F/ '{print $3}')"

# 单独 COPY requirements 稳住依赖层
COPY requirements.txt .
RUN pip install --no-compile -r requirements.txt

# 体积瘦身:清掉测试代码、文档、编译产物
RUN find /usr/local/lib/python3.12/site-packages -type d \
        \( -name 'tests' -o -name 'test' -o -name 'docs' -o -name 'doc' -o -name '__pycache__' \) \
        -exec rm -rf {} + 2>/dev/null || true && \
    find /usr/local/lib/python3.12/site-packages -name '*.pyc' -delete && \
    find /usr/local/lib/python3.12/site-packages -name '*.so' -exec strip --strip-unneeded {} + 2>/dev/null || true && \
    find /usr/local/lib/python3.12/site-packages -name '*.dist-info' -type d \
        -exec sh -c 'rm -f "$1"/RECORD && rmdir "$1" 2>/dev/null || true' _ {} \; 2>/dev/null || true

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim-bookworm AS runtime
ARG DEBIAN_MIRROR
ARG DEBIAN_SECURITY_MIRROR

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

# 运行时只装 libpq5(psycopg 运行需要)+ curl(健康检查用)
# tzdata slim 镜像里已自带 zoneinfo,不用单独装
RUN rm -f /etc/apt/sources.list \
        /etc/apt/sources.list.d/*.list \
        /etc/apt/sources.list.d/*.sources && \
    cat > /etc/apt/sources.list <<EOF
deb ${DEBIAN_MIRROR} bookworm main contrib non-free non-free-firmware
deb ${DEBIAN_MIRROR} bookworm-updates main contrib non-free non-free-firmware
deb ${DEBIAN_SECURITY_MIRROR} bookworm-security main contrib non-free non-free-firmware
EOF
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 curl \
        && rm -rf /var/lib/apt/lists/*

# 非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /bin/bash appuser

WORKDIR /app

# 从 builder 复制已清理的 site-packages(不带 bin)
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

# 项目代码(用 .dockerignore 排除 .pyc、__pycache__、tests、.git、*.md 等)
COPY . .

# 双保险清理
RUN find /usr/local/lib/python3.12/site-packages -name '*.pyc' -delete && \
    find /usr/local/lib/python3.12/site-packages -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true && \
    rm -rf /root/.cache /tmp/* /var/lib/apt/lists/* && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# 用 python -m 启动,避免依赖 /usr/local/bin 里的命令
CMD ["python", "-m", "uvicorn", "ServiceHealthInspection.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
