import pytest
from datetime import datetime, timezone

from services.core.app.generative import service
from services.core.app.generative.models import GenerativePreset


@pytest.mark.asyncio
async def test_get_preset_by_slug_round_trip(db_session):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    preset = GenerativePreset(
        slug="neo-tokyo",
        title="Neo Tokyo",
        description="d",
        prompt="cinematic still",
        preview_image_url="https://example.com/x.jpg",
        sort_order=10,
        created_at=now,
        updated_at=now,
    )
    db_session.add(preset)
    await db_session.commit()

    fetched = await service.get_preset_by_slug(db_session, "neo-tokyo")
    assert fetched is not None
    assert fetched.title == "Neo Tokyo"
    assert fetched.prompt == "cinematic still"


@pytest.mark.asyncio
async def test_get_preset_by_slug_missing(db_session):
    result = await service.get_preset_by_slug(db_session, "does-not-exist")
    assert result is None


@pytest.mark.asyncio
async def test_get_all_presets_ordered(db_session):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.add_all(
        [
            GenerativePreset(
                slug="b",
                title="B",
                prompt="p",
                preview_image_url="u",
                sort_order=20,
                created_at=now,
                updated_at=now,
            ),
            GenerativePreset(
                slug="a",
                title="A",
                prompt="p",
                preview_image_url="u",
                sort_order=10,
                created_at=now,
                updated_at=now,
            ),
        ]
    )
    await db_session.commit()

    results = await service.get_all_presets(db_session)
    assert [p.slug for p in results] == ["a", "b"]
