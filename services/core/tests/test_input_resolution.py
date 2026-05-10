import pytest
from datetime import datetime, timezone

from fastapi import HTTPException

from services.core.app.generative.models import GenerativePreset
from services.core.app.pipelines.input_resolution import resolve_pipeline_input


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_generative_editing_resolves_prompt_from_slug(db_session):
    now = _now()
    db_session.add(
        GenerativePreset(
            slug="neo-tokyo",
            title="Neo Tokyo",
            prompt="cinematic still in neon",
            preview_image_url="u",
            sort_order=10,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    resolved = await resolve_pipeline_input(
        db_session,
        "generative_editing",
        {"image_bucket": "b", "image_key": "k", "preset_slug": "neo-tokyo"},
    )

    assert resolved["prompt"] == "cinematic still in neon"
    assert resolved["preset_slug"] == "neo-tokyo"
    assert resolved["image_bucket"] == "b"


@pytest.mark.asyncio
async def test_generative_editing_unknown_slug_400(db_session):
    with pytest.raises(HTTPException) as exc:
        await resolve_pipeline_input(
            db_session,
            "generative_editing",
            {"preset_slug": "missing"},
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_generative_editing_missing_slug_400(db_session):
    with pytest.raises(HTTPException) as exc:
        await resolve_pipeline_input(
            db_session,
            "generative_editing",
            {},
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_other_pipeline_passes_input_through(db_session):
    payload = {"a": 1, "b": "x"}
    resolved = await resolve_pipeline_input(db_session, "face_swap", payload)
    assert resolved == payload
