# E2E Tests

## Running Locally

1. Create `.env` file in this directory with:

```bash
CORE_API_URL=http://localhost:8081
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
TEST_USER_EMAIL=test@example.com
TEST_USER_PASSWORD=your-test-password
```

2. Install dependencies:

```bash
cd services/common/tests
uv pip install httpx supabase
```

3. Run the test:

```bash
make test-e2e
```

Or run directly:

```bash
cd services/common/tests
source .env
uv run python e2e_recast_pipeline_test.py
```

## What It Tests

- Authentication with Supabase
- Fetching templates from recast API
- Queuing a pipeline job
- Polling for completion
- Downloading result image

