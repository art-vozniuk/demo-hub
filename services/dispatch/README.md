# Dispatch

Async orchestration worker. Drains the `pipelines.dispatch` RabbitMQ
queue and invokes remote inference (currently Modal). IO-bound by
design — no torch/onnx dependencies, no GPU.

## Pipelines

- `generative_editing` — image-conditioned editing via FLUX.2 klein on
  Modal GPU. See [services/modal](../modal).

## Local

Worker runs alongside `compute` in `docker-compose.local.yml`. Required
env vars (typically supplied via `services/dispatch/.env.docker`):

```
RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/
REDIS_URL=redis://redis:6379
MODAL_GENERATIVE_ENDPOINT_URL=https://<workspace>--demo-hub-flux-generate-endpoint.modal.run
MODAL_PROXY_AUTH_TOKEN_ID=...
MODAL_PROXY_AUTH_TOKEN_SECRET=...
S3_* (same vars as compute, used for upload/download)
```
