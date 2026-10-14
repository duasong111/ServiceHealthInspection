# ============================================================
# 多阶段构建:builder 装依赖 → runtime 只带运行时需要的
# ============================================================

# ---------- Stage 1: builder ----------
FROM python:3.12-slim-bookworm AS builder

# 系统依赖(编译阶段需要)
RUN rm -f /etc/apt/sources.list.d/debian.sources && \
    printf "deb https://mirrors.aliyun.com/debian/ bookworm main contrib non-free non-free-firmware\n" \
        > /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        libpq-dev \
        default-libmysqlclient-dev \
        libgl1 \
        libglib2.0-0 \
        && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 用清华源加速 pip
RUN python -m pip install --upgrade pip -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/ && \
    pip config set global.index-url https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/ && \
    pip config set global.trusted-host mirrors.tuna.tsinghua.edu.cn

# 先 COPY requirements 单独一层(依赖不变就不重新安装)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim-bookworm AS runtime

RUN rm -f /etc/apt/sources.list.d/debian.sources && \
    printf "deb https://mirrors.aliyun.com/debian/ bookworm main contrib non-free non-free-firmware\n" \
        > /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libpq5 \
        tzdata \
        curl \
        && \
    rm -rf /var/lib/apt/lists/*

# 时区
ENV TZ=Asia/Shanghai

# 非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /bin/bash appuser

WORKDIR /app

# 从 builder 复制已安装的 Python 包
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制项目代码
COPY . .

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=ServiceHealthInspection.settings \
    PORT=8000

# 镜像本身只承载 web 进程;celery worker / beat 用同一镜像但通过 docker-compose 覆盖 command
CMD ["uvicorn", "ServiceHealthInspection.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
