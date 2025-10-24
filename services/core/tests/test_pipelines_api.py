import pytest
from uuid import uuid4
from httpx import AsyncClient, ASGITransport

from services.core.main import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_queue_pipelines_unauthorized(client):
    response = await client.post(
        "/api/v1/pipelines/queue",
        json={
            "trace_id": str(uuid4()),
            "jobs": [
                {
                    "pipeline_id": str(uuid4()),
                    "pipeline_name": "test",
                    "input": {},
                }
            ],
        },
    )

    assert response.status_code in [401, 403]


@pytest.mark.asyncio
async def test_get_pipeline_status_unauthorized(client):
    response = await client.post(
        "/api/v1/pipelines/status",
        json={"pipeline_ids": [str(uuid4())]},
    )

    assert response.status_code in [401, 403]
