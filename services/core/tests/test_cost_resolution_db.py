"""DB-backed end-to-end test for resolve_cost: rules live in the
pipeline_cost_multipliers table, are loaded by pipeline_type_id, and
compose multiplicatively over base_cost.
"""

import pytest

from services.core.app.pipelines.cost_resolution import resolve_cost
from services.core.app.wallet.models import CostMultiplier, PipelineType


@pytest.mark.asyncio
async def test_resolve_cost_no_rules_returns_base(db_session):
    pt = PipelineType(name="solo", base_cost=10)
    db_session.add(pt)
    await db_session.commit()
    await db_session.refresh(pt)

    out = await resolve_cost(
        db_session,
        pipeline_type_id=pt.id,
        base_cost=pt.base_cost,
        pipeline_input={"anything": "goes"},
    )
    assert out == 10


@pytest.mark.asyncio
async def test_resolve_cost_with_single_rule(db_session):
    pt = PipelineType(name="quality", base_cost=10)
    db_session.add(pt)
    await db_session.commit()
    await db_session.refresh(pt)

    db_session.add(
        CostMultiplier(
            pipeline_type_id=pt.id,
            type="input_field",
            params={
                "input_field": "num_inference_steps",
                "values": {"2": 70, "4": 100, "8": 150},
            },
        )
    )
    await db_session.commit()

    assert await resolve_cost(db_session, pt.id, 10, {"num_inference_steps": 2}) == 7
    assert await resolve_cost(db_session, pt.id, 10, {"num_inference_steps": 4}) == 10
    assert await resolve_cost(db_session, pt.id, 10, {"num_inference_steps": 8}) == 15


@pytest.mark.asyncio
async def test_resolve_cost_stacks_rules_multiplicatively(db_session):
    pt = PipelineType(name="stack", base_cost=10)
    db_session.add(pt)
    await db_session.commit()
    await db_session.refresh(pt)

    db_session.add_all(
        [
            CostMultiplier(
                pipeline_type_id=pt.id,
                type="input_field",
                params={"input_field": "quality", "values": {"high": 150}},
            ),
            CostMultiplier(
                pipeline_type_id=pt.id,
                type="input_field",
                params={"input_field": "resolution", "values": {"4k": 200}},
            ),
        ]
    )
    await db_session.commit()

    # base 10 * 150% * 200% = 30
    out = await resolve_cost(
        db_session, pt.id, 10, {"quality": "high", "resolution": "4k"}
    )
    assert out == 30


@pytest.mark.asyncio
async def test_resolve_cost_unknown_handler_treated_as_identity(db_session):
    pt = PipelineType(name="bad", base_cost=10)
    db_session.add(pt)
    await db_session.commit()
    await db_session.refresh(pt)

    db_session.add(
        CostMultiplier(
            pipeline_type_id=pt.id,
            type="does_not_exist",
            params={"foo": "bar"},
        )
    )
    await db_session.commit()

    out = await resolve_cost(db_session, pt.id, 10, {})
    assert out == 10
