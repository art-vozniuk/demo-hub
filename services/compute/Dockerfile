ARG BASE_IMAGE=nvidia/cuda:12.8.1-runtime-ubuntu22.04
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    tzdata software-properties-common wget git curl build-essential g++ \
    libssl-dev zlib1g-dev libffi-dev libgl1 libglib2.0-0 libsm6 gpg gpg-agent && \
    ln -fs /usr/share/zoneinfo/$TZ /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.13 python3.13-venv python3.13-dev && \
    rm -rf /var/lib/apt/lists/*

RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.13
RUN python3.13 -m pip install --no-cache-dir -U uv

WORKDIR /app

COPY services/compute/pyproject.toml services/compute/uv.lock ./services/compute/
COPY services/common/pyproject.toml ./services/common/
COPY services/external/face_swap/pyproject.toml ./services/external/face_swap/

RUN uv sync --python python3.13 --project ./services/compute --frozen --no-install-project --no-dev

COPY services/compute ./services/compute
COPY services/common ./services/common
COPY services/external/face_swap ./services/external/face_swap

RUN --mount=type=secret,id=env,target=/tmp/.env \
    if [ -f /tmp/.env ]; then \
        cp /tmp/.env /app/.env && \
        chmod 644 /app/.env; \
    else \
        echo "No .env secret provided, skipping (use --env-file at runtime)"; \
    fi

ENV PATH="/app/services/compute/.venv/bin:$PATH"
ENV PYTHONPATH="/app:/app/services/compute:/app/services/external/face_swap"

ARG BUILD_TAG=unknown
ENV BUILD_TAG=${BUILD_TAG}

WORKDIR /app/services/compute
CMD sh -c 'if [ -f /app/.env ]; then export $(cat /app/.env | xargs); fi && python3.13 main.py'