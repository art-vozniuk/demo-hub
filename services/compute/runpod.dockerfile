FROM runpod/pytorch:1.0.1-cu1281-torch271-ubuntu2204

WORKDIR /app

RUN pip install --upgrade pip && pip install uv

COPY services/compute/pyproject.toml services/compute/uv.lock ./services/compute/
COPY services/common/pyproject.toml ./services/common/
COPY services/external/face_swap/pyproject.toml ./services/external/face_swap/

RUN uv sync --project ./services/compute --frozen --no-install-project --no-dev

COPY services/compute ./services/compute
COPY services/common ./services/common
COPY services/external/face_swap ./services/external/face_swap

ENV PATH="/app/services/compute/.venv/bin:$PATH"
ENV PYTHONPATH="/app:/app/services/compute:/app/services/external/face_swap"

ARG BUILD_TAG=unknown
ENV BUILD_TAG=${BUILD_TAG}

WORKDIR /app/services/compute
CMD ["python", "main.py"]