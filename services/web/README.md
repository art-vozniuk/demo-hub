# Web Service

Frontend interface for the Demo Hub platform.

## Purpose

The Web service provides a user-facing interface for interacting with the ML pipelines. It handles authentication, file uploads, job submission, and result display.

## Tech Stack

- React 18 with TypeScript
- Vite - Fast build tooling
- TailwindCSS - Utility-first styling
- shadcn/ui - Component library
- React Router - Client-side routing

## Note on Code Quality

This frontend was built rapidly to demonstrate the backend capabilities and provide a functional interface for the live demo. While it successfully showcases end-to-end functionality from UI to ML inference, the TypeScript and React implementation prioritizes speed of development over architectural patterns. It serves its purpose as a working demo interface.

## Features

- **Authentication** - Integration with Supabase Auth
- **File Upload** - Direct upload to S3-compatible storage
- **Job Management** - Submit jobs and poll for status
- **Result Display** - Show processed images and outputs
- **Responsive Design** - Works on desktop and mobile

## Project Structure

```
src/
├── api/              # API client and types
├── components/       # Reusable UI components
├── contexts/         # React contexts (auth, etc)
├── hooks/            # Custom React hooks
├── pages/            # Page components
└── lib/              # Utility functions
```

## Configuration

Key environment variables (see `.env.example` in the service directory):

- `VITE_CORE_API_URL` - Core service API endpoint
- `VITE_SUPABASE_URL` - Supabase project URL
- `VITE_SUPABASE_ANON_KEY` - Supabase anonymous key

