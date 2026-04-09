# Demo Hub

Personal demo hub for showcasing side projects — ML experiments, real-time rendering, and other things I build.

## Live

**[artemv.tech](https://artemv.tech)**

### Try Style

Upload a portrait and apply it to various style templates using a GAN-based image generation pipeline.

<img width="891" height="796" alt="image" src="https://github.com/user-attachments/assets/dcf22caa-6754-4239-85f5-28a5c8fbf4af" />
<img width="1009" height="502" alt="image" src="https://github.com/user-attachments/assets/44e47bcb-6e89-44d6-b0d4-21a0ebffb1e8" />
<img width="1019" height="510" alt="image" src="https://github.com/user-attachments/assets/9a445ec5-3ab7-42be-a36f-67fac2f8f058" />

### 3D Renderer

Real-time 3D renderer running in the browser. Built from scratch in C++ with a custom engine, compiled to WebAssembly via Emscripten and powered by WebGL 2.

Source: [OpenGL-Renderer](https://github.com/art-vozniuk/OpenGL-Renderer)

## Tech Stack

**Backend** — FastAPI, PostgreSQL, RabbitMQ, Redis, Nginx

**ML/AI** — PyTorch, ONNX Runtime, custom GAN pipeline

**3D Renderer** — C++, OpenGL, Emscripten, WebAssembly, WebGL 2

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
│   └── external/        # OpenGL-Renderer submodule, face_swap
├── nginx/               # Reverse proxy config
├── scripts/             # Build scripts (renderer, etc.)
├── docker-compose.yml
└── Makefile
```
