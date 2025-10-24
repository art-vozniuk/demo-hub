# Compute Service

Isolated ML inference workers for the Demo Hub platform.

## Purpose

The Compute service is a dedicated worker that handles resource-intensive ML inference tasks. It runs independently from the API layer, allowing for flexible scaling on GPU or CPU hardware without affecting the core service.

## Responsibilities

- **Job Consumption** - Listens to RabbitMQ queue for incoming inference requests
- **ML Inference** - Loads models and runs predictions on GPU or CPU
- **S3 Integration** - Downloads input images, uploads processed results
- **Status Updates** - Publishes pipeline status back to RabbitMQ for core service
- **Error Handling** - Catches and reports inference failures gracefully

## Key Features

### RabbitMQ Integration
- **Consumer** - Pulls jobs from the main queue with configurable prefetch
- **Publisher** - Sends status updates (processing, completed, failed) back to core

### Pipeline Architecture

The service uses a factory pattern for different ML pipelines:

```python
pipeline_templates = {
    "recast": PipelineType(
        service_type=RecastService,
        pipeline_type=RecastPipeline,
        input_type=RecastPipelineInput,
    ),
}
```

Each pipeline consists of:
- **Service** - Handles I/O operations (S3 downloads/uploads)
- **Pipeline** - Contains the actual ML inference logic
- **Input Schema** - Pydantic validation for job parameters

### GPU/CPU Support

The service automatically detects available hardware and configures inference accordingly. GPU acceleration is used when available, with automatic fallback to CPU.

### Model Management

Models are downloaded from S3 on first use and cached locally. The service checks for existing models before downloading to speed up subsequent runs.

### Inference Serialization

A global async lock ensures GPU operations don't conflict when processing multiple jobs concurrently, preventing out-of-memory errors.

## Configuration

Key environment variables (see `.env.example` in the service directory):

- `RABBITMQ_URL` - RabbitMQ connection string
- `RABBITMQ_PREFETCH` - Number of jobs to prefetch (default: 1)
- `SUPABASE_URL` - Supabase project URL for S3
- `SUPABASE_KEY` - Supabase service key
- `SENTRY_DSN` - Sentry error tracking

