FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get -o Acquire::Retries=3 update && \
    apt-get install -y --no-install-recommends \
    build-essential ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -U uv

WORKDIR /app

COPY services/dispatch/pyproject.toml ./services/dispatch/
COPY services/common/pyproject.toml ./services/common/

RUN cd services/common && uv pip install --system -e .
RUN cd services/dispatch && uv pip install --system -e .

COPY services/common/ ./services/common/
COPY services/dispatch/ ./services/dispatch/

RUN --mount=type=secret,id=env,target=/tmp/.env,required=false \
    if [ -f /tmp/.env ]; then \
        cp /tmp/.env /app/.env && chmod 644 /app/.env; \
    fi

ENV PYTHONPATH="/app:/app/services/dispatch"

ARG BUILD_TAG=unknown
ENV BUILD_TAG=${BUILD_TAG}

WORKDIR /app/services/dispatch
CMD sh -c 'if [ -f /app/.env ]; then export $(grep -vE "^[[:space:]]*#" /app/.env | xargs); fi && python main.py'
