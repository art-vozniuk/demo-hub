# Demo Hub

Personal demo hub for showcasing side projects.

## Live

**[artemv.tech](https://artemv.tech)**

### Gaussian Spatting

Gaussian Splatting renderer running entirely in the browser. Custom C++
WebGPU engine, every-frame GPU radix sort + EWA splat projection in WGSL.
Same code path runs natively on macOS via Dawn → Metal.

<img width="1135" height="717" alt="image" src="https://github.com/user-attachments/assets/18502ab7-9bba-4109-8a3e-29f1b775ff26" />


Source: [renderer](https://github.com/art-vozniuk/renderer)

### Face Swap

Upload a portrait and apply it to various style templates using a GAN-based image generation pipeline.

<img width="891" height="796" alt="image" src="https://github.com/user-attachments/assets/dcf22caa-6754-4239-85f5-28a5c8fbf4af" />
<img width="1009" height="502" alt="image" src="https://github.com/user-attachments/assets/44e47bcb-6e89-44d6-b0d4-21a0ebffb1e8" />
<img width="1019" height="510" alt="image" src="https://github.com/user-attachments/assets/9a445ec5-3ab7-42be-a36f-67fac2f8f058" />

## Tech Stack

**Backend** — FastAPI, PostgreSQL, RabbitMQ, Redis, Nginx

**ML/AI** — PyTorch, ONNX Runtime, custom GAN pipeline

**Renderer** — C++, WebGPU, WGSL, Dawn / emdawnwebgpu, Emscripten, WebAssembly

**Frontend** — React, TypeScript, Vite, TailwindCSS

**Infra** — Docker, GitHub Actions, Supabase, Sentry

## Architecture

- **Core** — API gateway: auth, rate limiting, job orchestration
- **Compute** — ML inference workers consuming from RabbitMQ
- **Web** — React SPA
- **Renderer** — Emscripten WASM build served via Supabase Storage + GitHub Releases

## Project Structure

```
demo-hub/
├── services/
│   ├── common/          # Shared: auth, db, rabbitmq, redis, s3
│   ├── core/            # API gateway
│   ├── compute/         # ML workers
│   ├── web/             # React frontend
│   └── external/        # renderer + face_swap submodules
├── nginx/               # Reverse proxy config
├── scripts/             # Build scripts (renderer, etc.)
├── docker-compose.yml
└── Makefile
```
