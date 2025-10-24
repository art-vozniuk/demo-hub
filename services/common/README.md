# Common Package

Shared library for the Demo Hub platform containing reusable components and integrations.

## Purpose

The Common package provides a unified set of utilities, clients, and patterns used across all services. This approach ensures consistency, reduces code duplication, and makes it easier to update shared functionality.

## What's Included

### Authentication
- JWT token validation with JWKS
- Supabase Auth integration
- User models and dependencies
- Optional authentication support

### Database
- SQLAlchemy async ORM configuration
- Alembic migrations setup
- Database connection pooling
- Session management and dependencies
- Health check middleware

### RabbitMQ
- Connection management with retry logic
- Publisher for sending messages
- Consumer for receiving messages
- Health checks and graceful shutdown
- Configurable queues and routing keys

### Redis
- Async Redis client
- Rate limiting implementation
- Connection pooling
- Key expiration management

### S3
- Supabase Storage client (S3-compatible)
- File upload/download operations
- Presigned URL generation
- Bucket management

### Middleware
- Exception handling middleware
- Request/response logging
- Error formatting

### Logging
- Structured logging configuration
- Sentry integration
- Log level management
- Request ID tracking

### Domain Models
- Shared enums (PipelineStatus, etc)
- Common data structures
