FROM python:3.11-slim

WORKDIR /app

RUN pip install uv

COPY services/core/pyproject.toml services/core/
COPY services/common/pyproject.toml services/common/

RUN cd services/core && uv pip install --system -e .
RUN cd services/common && uv pip install --system -e .

COPY services/common/ services/common/
COPY services/core/ services/core/

RUN --mount=type=secret,id=env,target=/tmp/.env \
    cp /tmp/.env /app/.env && \
    chmod 644 /app/.env

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

ARG BUILD_TAG=unknown
ENV BUILD_TAG=${BUILD_TAG}

EXPOSE 8081

CMD sh -c 'export $(cat /app/.env | xargs) && uvicorn services.core.main:app --host 0.0.0.0 --port 8081'

