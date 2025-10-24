import pytest

from services.core.app.recast import service
from services.core.app.recast.models import RecastTemplate


@pytest.mark.asyncio
async def test_get_all_templates_empty(db_session):
    templates = await service.get_all_templates(db_session)
    assert templates == []


@pytest.mark.asyncio
async def test_get_template_by_id_not_found(db_session):
    template = await service.get_template_by_id(db_session, 999)
    assert template is None


@pytest.mark.asyncio
async def test_get_all_templates(db_session):
    template1 = RecastTemplate(
        name="Template 1",
        description="Test template 1",
        url="https://example.com/1.jpg",
    )
    template2 = RecastTemplate(
        name="Template 2",
        description="Test template 2",
        url="https://example.com/2.jpg",
    )

    db_session.add(template1)
    db_session.add(template2)
    await db_session.commit()

    templates = await service.get_all_templates(db_session)

    assert len(templates) == 2


@pytest.mark.asyncio
async def test_get_template_by_id(db_session):
    template = RecastTemplate(
        name="Test Template",
        description="Test description",
        url="https://example.com/template.jpg",
    )

    db_session.add(template)
    await db_session.commit()
    await db_session.refresh(template)

    found = await service.get_template_by_id(db_session, template.id)

    assert found is not None
    assert found.id == template.id
    assert found.url == "https://example.com/template.jpg"
