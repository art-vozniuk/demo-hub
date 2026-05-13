import pytest
from uuid import uuid4

from services.common.domain.enums import PipelineStatus
from services.core.app.pipelines import service


@pytest.mark.asyncio
async def test_create_pipeline(db_session):
    pipeline_id = uuid4()
    trace_id = uuid4()
    pipeline_name = "test_pipeline"
    input_payload = {"image_url": "https://example.com/x.png", "k": 3}

    pipeline = await service.create_pipeline(
        db=db_session,
        pipeline_id=pipeline_id,
        trace_id=trace_id,
        pipeline_name=pipeline_name,
        input=input_payload,
    )

    assert pipeline.id == pipeline_id
    assert pipeline.trace_id == trace_id
    assert pipeline.pipeline_name == pipeline_name
    assert pipeline.status == PipelineStatus.PENDING
    assert pipeline.input == input_payload
    assert pipeline.result is None
    assert pipeline.message is None


@pytest.mark.asyncio
async def test_create_pipeline_without_input(db_session):
    pipeline = await service.create_pipeline(
        db=db_session,
        pipeline_id=uuid4(),
        trace_id=uuid4(),
        pipeline_name="test_pipeline",
    )

    assert pipeline.input is None


@pytest.mark.asyncio
async def test_update_pipeline_status_face_swap_result(db_session):
    pipeline_id = uuid4()
    trace_id = uuid4()

    await service.create_pipeline(
        db=db_session,
        pipeline_id=pipeline_id,
        trace_id=trace_id,
        pipeline_name="face_swap",
    )

    updated = await service.update_pipeline_status(
        db=db_session,
        pipeline_id=pipeline_id,
        status=PipelineStatus.COMPLETED,
        result={"result_url": "https://example.com/result.png"},
        message="success",
    )

    assert updated is not None
    assert updated.status == PipelineStatus.COMPLETED
    assert updated.result == {"result_url": "https://example.com/result.png"}
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
async def test_update_pipeline_status_face_recognition_result(db_session):
    pipeline_id = uuid4()
    trace_id = uuid4()

    await service.create_pipeline(
        db=db_session,
        pipeline_id=pipeline_id,
        trace_id=trace_id,
        pipeline_name="face_recognition",
    )

    result = {
        "image_width": 800,
        "image_height": 600,
        "faces": [{"id": "f0", "bbox": [10, 20, 30, 40], "det_score": 0.99}],
    }

    await service.update_pipeline_status(
        db=db_session,
        pipeline_id=pipeline_id,
        status=PipelineStatus.COMPLETED,
        result=result,
        message="success",
    )

    pipelines = await service.get_pipelines_by_ids(db_session, [pipeline_id])
    assert len(pipelines) == 1
    assert pipelines[0].result == result


@pytest.mark.asyncio
async def test_create_pipeline_with_user_id(db_session):
    user_id = uuid4()
    pipeline = await service.create_pipeline(
        db=db_session,
        pipeline_id=uuid4(),
        trace_id=uuid4(),
        pipeline_name="face_swap",
        user_id=user_id,
    )

    assert pipeline.user_id == user_id


@pytest.mark.asyncio
async def test_list_pipelines_for_user_filters_and_orders(db_session):
    user_a = uuid4()
    user_b = uuid4()

    for name in ("face_recognition", "face_swap", "generative_editing"):
        await service.create_pipeline(
            db=db_session,
            pipeline_id=uuid4(),
            trace_id=uuid4(),
            pipeline_name=name,
            user_id=user_a,
        )
    await service.create_pipeline(
        db=db_session,
        pipeline_id=uuid4(),
        trace_id=uuid4(),
        pipeline_name="face_swap",
        user_id=user_b,
    )

    result_a = await service.list_pipelines_for_user(
        db_session, user_a, limit=50, offset=0
    )
    assert len(result_a) == 3
    assert {p.user_id for p in result_a} == {user_a}
    # Newest first.
    timestamps = [p.created_at for p in result_a]
    assert timestamps == sorted(timestamps, reverse=True)

    result_b = await service.list_pipelines_for_user(
        db_session, user_b, limit=50, offset=0
    )
    assert len(result_b) == 1
    assert result_b[0].pipeline_name == "face_swap"


@pytest.mark.asyncio
async def test_list_pipelines_for_user_pagination(db_session):
    user_id = uuid4()
    for _ in range(5):
        await service.create_pipeline(
            db=db_session,
            pipeline_id=uuid4(),
            trace_id=uuid4(),
            pipeline_name="face_swap",
            user_id=user_id,
        )

    page1 = await service.list_pipelines_for_user(
        db_session, user_id, limit=2, offset=0
    )
    page2 = await service.list_pipelines_for_user(
        db_session, user_id, limit=2, offset=2
    )

    assert len(page1) == 2
    assert len(page2) == 2
    assert {p.id for p in page1}.isdisjoint({p.id for p in page2})

    total = await service.count_pipelines_for_user(db_session, user_id)
    assert total == 5


@pytest.mark.asyncio
async def test_count_pipelines_for_user_returns_zero_for_unknown(db_session):
    total = await service.count_pipelines_for_user(db_session, uuid4())
    assert total == 0


@pytest.mark.asyncio
async def test_update_pipeline_status_overwrites_result(db_session):
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
        result={"faces": []},
    )

    await service.update_pipeline_status(
        db=db_session,
        pipeline_id=pipeline_id,
        status=PipelineStatus.COMPLETED,
        result={"faces": [{"id": "f0", "bbox": [1, 2, 3, 4]}]},
    )

    pipelines = await service.get_pipelines_by_ids(db_session, [pipeline_id])
    assert pipelines[0].result == {"faces": [{"id": "f0", "bbox": [1, 2, 3, 4]}]}
