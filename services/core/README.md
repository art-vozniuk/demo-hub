# Core Service

API gateway and orchestration service for the Demo Hub platform.

## Purpose

The Core service acts as the primary HTTP API layer, handling client requests, authentication, rate limiting, and job orchestration. It manages the lifecycle of ML inference jobs by publishing to RabbitMQ and tracking status in PostgreSQL.

## Responsibilities

- **HTTP API** - RESTful endpoints for job submission and status tracking
- **Authentication** - JWT validation with JWKS via Supabase
- **Authorization** - User-based access control
- **Rate Limiting** - Redis-backed per-user request limits
- **Database Operations** - Pipeline status tracking, user data management
- **Job Queue Management** - Publishes jobs to RabbitMQ for compute workers
- **Status Updates** - Consumes pipeline status updates from compute workers
- **Database Migrations** - Alembic for schema versioning

## Key Features

### RabbitMQ Integration
- **Publisher** - Submits jobs to the compute queue with structured messages
- **Consumer** - Receives status updates from compute workers asynchronously

### Database Layer
- SQLAlchemy ORM with async support
- Alembic migrations for version control
- Connection pooling and health checks

### Shared Common Package
Integrates the shared `common` package for:
- Auth utilities
- Database configuration
- RabbitMQ pub/sub
- Redis client
- S3 operations
- Exception middleware
- Logging setup

## API Endpoints

### Pipelines
- `POST /pipelines/queue` - Submit one or more jobs for processing
- `POST /pipelines/status` - Get status of submitted jobs

### Recast (Example Domain)
- `POST /recast/templates` - List available templates
- Additional endpoints for specific features

## Configuration

Key environment variables (see `.env.example` in the service directory):

- `DATABASE_URL` - PostgreSQL connection string
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_KEY` - Supabase service key
- `RABBITMQ_URL` - RabbitMQ connection string
- `REDIS_URL` - Redis connection string
- `SENTRY_DSN` - Sentry error tracking
- `RATE_LIMIT_QUEUE_PER_MINUTE` - Max job submissions per minute per user
- `MAX_PIPELINES_PER_REQUEST` - Max jobs in a single request

