# Demo Hub

A production-ready MVP template for building AI-powered products with microservices architecture, async job processing, and scalable infrastructure.

**Live Demo:** [artemv.tech/face-fusion](https://artemv.tech/face-fusion)

## Overview

This project demonstrates a complete end-to-end implementation of an AI product, from frontend to ML inference, with production patterns for authentication, rate limiting, job queuing, and observability. It serves as a practical template for rapidly building and deploying AI MVPs while maintaining code quality and scalability.

## Key Features

- **Microservices Architecture** - Separation of API layer and compute workers for independent scaling
- **Async Job Processing** - RabbitMQ-based pub/sub pattern for handling long-running ML inference
- **Dual Infrastructure Setup** - Core services (lightweight) and compute workers (GPU/CPU) deployed to different VPS configurations
- **Production Auth** - JWT authentication with JWKS validation via Supabase
- **Rate Limiting** - Redis-based per-user rate limiting
- **Database Migrations** - Alembic for schema versioning
- **Observability** - Sentry integration for error tracking and monitoring
- **CI/CD** - Automated builds and deployments via GitHub Actions
- **Modern Python Tooling** - Fast dependency management with `uv`, linting with `ruff`, testing with `pytest`

## Tech Stack

**Backend**
- FastAPI - High-performance async API framework
- PostgreSQL - Primary database (via Supabase)
- RabbitMQ - Message broker for job queue
- Redis - Caching and rate limiting
- Nginx - Reverse proxy with automatic SSL (Let's Encrypt)

**ML/AI**
- PyTorch - Deep learning framework
- Custom GAN pipeline - Optimized inference for image processing

**Infrastructure & Services**
- Docker - Containerization
- GitHub Actions - CI/CD automation
- Supabase - Authentication, database hosting, and S3-compatible storage
- Sentry - Error tracking and performance monitoring

**Frontend**
- React with TypeScript
- Vite - Fast build tooling
- TailwindCSS - Styling

## Architecture

The system is split into three main services:

**Core Service** - HTTP API gateway handling authentication, rate limiting, database operations, and job orchestration. Publishes jobs to RabbitMQ and consumes status updates.

**Compute Service** - Isolated workers for ML inference. Consumes jobs from RabbitMQ, runs inference on GPU/CPU, uploads results to S3, and publishes status updates. Can be scaled horizontally on different hardware.

**Web Service** - React frontend for interacting with the API and displaying results.

**Common Package** - Shared library containing reusable components: auth, database, RabbitMQ, Redis, S3 clients, middleware, and logging configuration.

This architecture enables:
- Independent scaling of compute resources
- Cost optimization by running heavy workloads on dedicated hardware
- Easy addition of new ML pipelines without touching the API layer
- Horizontal scaling of workers for handling concurrent requests

## Current Demo: Try Style

The live demo showcases a style transfer feature where users upload a portrait photo and see it transformed with different artistic styles. The pipeline uses a GAN-based approach optimized for fast inference.

## Configuration

The repository includes `.env.example` files in the root directory and each service directory as templates for required environment variables.

### GitHub Secrets

If you fork this project and want to set up CI/CD, you'll need to configure the following secrets in your GitHub repository:

**Core Infrastructure:**
- `DATABASE_URL` - PostgreSQL connection string
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_ANON_KEY` - Supabase anonymous key
- `S3_ENDPOINT` - S3-compatible storage endpoint
- `S3_REGION` - S3 region
- `S3_ACCESS_KEY_ID` - S3 access key
- `S3_ACCESS_KEY_SECRET` - S3 secret key
- `S3_PUBLIC_BUCKETS_ENDPOINT` - Public URL for S3 buckets
- `RABBITMQ_USER` - RabbitMQ username
- `RABBITMQ_PASSWORD` - RabbitMQ password
- `SENTRY_DSN` - Sentry error tracking DSN
- `RATE_LIMIT_QUEUE_PER_MINUTE` - Rate limit for job submissions
- `RATE_LIMIT_STATUS_PER_MINUTE` - Rate limit for status checks
- `ALLOWED_ORIGINS` - CORS allowed origins
- `ENV` - Environment name (production/staging)

**Deployment:**
- `SERVER_HOST` - VPS hostname or IP
- `SERVER_USER` - SSH username for deployment
- `SSH_PRIVATE_KEY` - SSH private key for deployment access
- `GHCR_TOKEN` - GitHub Container Registry token for pushing images

**SSL/Domain:**
- `CERTBOT_EMAIL` - Email for Let's Encrypt certificates
- `CERTBOT_DOMAINS` - Domains for SSL certificates

**Frontend:**
- `VITE_APP_URL` - Frontend application URL
- `VITE_CORE_API_URL` - Core API endpoint URL

## Project Structure

```
demo-hub/
├── services/
│   ├── common/          # Shared package for auth, database, rabbitmq, redis, s3
│   ├── core/            # API gateway service
│   ├── compute/         # ML inference workers
│   ├── web/             # React frontend
│   └── external/        # Third-party integrations
├── nginx/               # Nginx configuration
├── docker-compose.yml   # Core infrastructure setup
├── docker-compose.compute.yml  # Compute worker setup
└── Makefile            # Development and deployment commands
```

See individual service READMEs for detailed information:
- [Core Service](services/core/README.md)
- [Compute Service](services/compute/README.md)
- [Web Service](services/web/README.md)
- [Common Package](services/common/README.md)
