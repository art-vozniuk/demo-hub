import pytest
from uuid import uuid4

from services.common.domain.enums import PipelineStatus
from services.core.app.pipelines import service


@pytest.mark.asyncio
async def test_create_pipeline(db_session):
    pipeline_id = uuid4()
    trace_id = uuid4()
    pipeline_name = "test_pipeline"

    pipeline = await service.create_pipeline(
        db=db_session,
        pipeline_id=pipeline_id,
        trace_id=trace_id,
        pipeline_name=pipeline_name,
    )

    assert pipeline.id == pipeline_id
    assert pipeline.trace_id == trace_id
    assert pipeline.pipeline_name == pipeline_name
    assert pipeline.status == PipelineStatus.PENDING
    assert pipeline.result_url is None
    assert pipeline.message is None


@pytest.mark.asyncio
async def test_update_pipeline_status(db_session):
    pipeline_id = uuid4()
    trace_id = uuid4()

    await service.create_pipeline(
        db=db_session,
        pipeline_id=pipeline_id,
        trace_id=trace_id,
        pipeline_name="test",
    )

    updated = await service.update_pipeline_status(
        db=db_session,
        pipeline_id=pipeline_id,
        status=PipelineStatus.COMPLETED,
        result_url="https://example.com/result.png",
        message="success",
    )

    assert updated is not None
    assert updated.status == PipelineStatus.COMPLETED
    assert updated.result_url == "https://example.com/result.png"
    assert updated.message == "success"


@pytest.mark.asyncio
async def test_update_pipeline_status_not_found(db_session):
    result = await service.update_pipeline_status(
        db=db_session,
        pipeline_id=uuid4(),
        status=PipelineStatus.COMPLETED,
    )

    assert result is None


@pytest.mark.asyncio
async def test_get_pipelines_by_ids(db_session):
    pipeline_id_1 = uuid4()
    pipeline_id_2 = uuid4()
    trace_id = uuid4()

    await service.create_pipeline(db_session, pipeline_id_1, trace_id, "test1")
    await service.create_pipeline(db_session, pipeline_id_2, trace_id, "test2")

    pipelines = await service.get_pipelines_by_ids(
        db=db_session,
        pipeline_ids=[pipeline_id_1, pipeline_id_2],
    )

    assert len(pipelines) == 2
    assert {p.id for p in pipelines} == {pipeline_id_1, pipeline_id_2}


@pytest.mark.asyncio
async def test_get_pipelines_by_ids_empty(db_session):
    pipelines = await service.get_pipelines_by_ids(
        db=db_session,
        pipeline_ids=[uuid4()],
    )

    assert len(pipelines) == 0


@pytest.mark.asyncio
async def test_update_pipeline_status_inserts_payload(db_session):
    pipeline_id = uuid4()
    trace_id = uuid4()

    await service.create_pipeline(
        db=db_session,
        pipeline_id=pipeline_id,
        trace_id=trace_id,
        pipeline_name="face_recognition",
    )

    payload = {
        "image_width": 800,
        "image_height": 600,
        "faces": [{"id": "f0", "bbox": [10, 20, 30, 40], "det_score": 0.99}],
    }

    await service.update_pipeline_status(
        db=db_session,
        pipeline_id=pipeline_id,
        status=PipelineStatus.COMPLETED,
        message="success",
        payload=payload,
    )

    stored = await service.get_pipeline_payload(db_session, pipeline_id)
    assert stored is not None
    assert stored.payload == payload


@pytest.mark.asyncio
async def test_update_pipeline_status_upserts_payload(db_session):
    pipeline_id = uuid4()
    trace_id = uuid4()

    await service.create_pipeline(
        db=db_session,
        pipeline_id=pipeline_id,
        trace_id=trace_id,
        pipeline_name="face_recognition",
    )

    await service.update_pipeline_status(
        db=db_session,
        pipeline_id=pipeline_id,
        status=PipelineStatus.RUNNING,
        payload={"faces": []},
    )

    await service.update_pipeline_status(
        db=db_session,
        pipeline_id=pipeline_id,
        status=PipelineStatus.COMPLETED,
        payload={"faces": [{"id": "f0", "bbox": [1, 2, 3, 4]}]},
    )

    stored = await service.get_pipeline_payload(db_session, pipeline_id)
    assert stored is not None
    assert stored.payload == {"faces": [{"id": "f0", "bbox": [1, 2, 3, 4]}]}


@pytest.mark.asyncio
async def test_get_pipelines_by_ids_loads_payload(db_session):
    pipeline_id = uuid4()
    trace_id = uuid4()

    await service.create_pipeline(
        db=db_session, pipeline_id=pipeline_id, trace_id=trace_id, pipeline_name="x"
    )

    payload = {"faces": [{"id": "f0", "bbox": [0, 0, 1, 1]}]}
    await service.update_pipeline_status(
        db=db_session,
        pipeline_id=pipeline_id,
        status=PipelineStatus.COMPLETED,
        payload=payload,
    )

    pipelines = await service.get_pipelines_by_ids(
        db=db_session, pipeline_ids=[pipeline_id]
    )
    assert len(pipelines) == 1
    assert pipelines[0].payload is not None
    assert pipelines[0].payload.payload == payload
