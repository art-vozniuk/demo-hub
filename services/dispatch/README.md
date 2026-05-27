# Dispatch

Async orchestration worker. Drains the `pipelines.dispatch` RabbitMQ
queue and invokes remote inference (currently Modal). IO-bound by
design — no torch/onnx dependencies, no GPU.

## Pipelines

- `generative_editing` — image + preset slug → edited image (FLUX.2
  klein on Modal GPU).
- `generative_editing_custom` — same Modal app, but the user supplies
  the prompt free-form (bypasses preset resolution).
- `generative_t2i` — pure text → image (FLUX.2 schnell on Modal GPU).
- `sharp` — single image → 3DGS scene (Apple ml-sharp on Modal GPU).
- `trellis` — single image → textured GLB mesh (Microsoft TRELLIS.2 on
  Modal GPU).

All five Modal apps expose the same submit + poll endpoint pair; shared
loop lives in `app/pipelines/modal_client.py:_submit_and_poll`. See
[services/modal](../modal).

## Local

Worker runs alongside `compute` in `docker-compose.local.yml`. Required
env vars (typically supplied via `services/dispatch/.env.docker`):

```
RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/
REDIS_URL=redis://redis:6379
MODAL_GENERATIVE_SUBMIT_URL=https://<workspace>--demo-hub-flux-submit.modal.run
MODAL_GENERATIVE_POLL_URL=https://<workspace>--demo-hub-flux-poll.modal.run
MODAL_GENERATIVE_T2I_SUBMIT_URL=https://<workspace>--demo-hub-flux-t2i-submit.modal.run
MODAL_GENERATIVE_T2I_POLL_URL=https://<workspace>--demo-hub-flux-t2i-poll.modal.run
MODAL_SHARP_SUBMIT_URL=https://<workspace>--demo-hub-sharp-submit.modal.run
MODAL_SHARP_POLL_URL=https://<workspace>--demo-hub-sharp-poll.modal.run
MODAL_TRELLIS_SUBMIT_URL=https://<workspace>--demo-hub-trellis-submit.modal.run
MODAL_TRELLIS_POLL_URL=https://<workspace>--demo-hub-trellis-poll.modal.run
MODAL_PROXY_AUTH_TOKEN_ID=...
MODAL_PROXY_AUTH_TOKEN_SECRET=...
S3_* (same vars as compute, used for upload/download)
```
