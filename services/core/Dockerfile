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

# Apply pending Alembic migrations on container start, then boot the API.
# This keeps prod DB schema in lockstep with the deployed code, so new
# tables/columns introduced by a release land before the first request hits
# them — previously migrations had to be applied manually and a missed run
# would surface as 500s the moment any endpoint touched the new schema.
CMD sh -c 'export $(cat /app/.env | xargs) && \
    cd services/core && alembic upgrade head && cd /app && \
    uvicorn services.core.main:app --host 0.0.0.0 --port 8081'

