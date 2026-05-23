import uuid

import pytest

from services.core.app.editor_scenes import service
from services.core.app.editor_scenes.models import EditorScene
from services.core.app.editor_scenes.service import DEFAULT_SCENE_ID


@pytest.mark.asyncio
async def test_create_and_get_scene(db_session):
    user_id = uuid.uuid4()
    scene = await service.create_scene(
        db_session,
        user_id=user_id,
        name="Untitled",
        manifest={"schema": 1, "name": "Untitled", "objects": []},
    )
    assert scene.name == "Untitled"
    assert scene.user_id == user_id

    found = await service.get_scene_for_user(db_session, user_id, scene.id)
    assert found is not None
    assert found.id == scene.id


@pytest.mark.asyncio
async def test_get_scene_for_other_user_returns_none(db_session):
    owner = uuid.uuid4()
    other = uuid.uuid4()
    scene = await service.create_scene(
        db_session,
        user_id=owner,
        name="Mine",
        manifest={"schema": 1, "name": "Mine", "objects": []},
    )
    # Owner sees it.
    assert await service.get_scene_for_user(db_session, owner, scene.id) is not None
    # Other user does not — keeps the API from leaking ownership.
    assert await service.get_scene_for_user(db_session, other, scene.id) is None


@pytest.mark.asyncio
async def test_list_scenes_for_user(db_session):
    a = uuid.uuid4()
    b = uuid.uuid4()
    await service.create_scene(db_session, user_id=a, name="A1", manifest={})
    await service.create_scene(db_session, user_id=a, name="A2", manifest={})
    await service.create_scene(db_session, user_id=b, name="B1", manifest={})
    items_a = await service.list_scenes_for_user(db_session, a)
    items_b = await service.list_scenes_for_user(db_session, b)
    assert {s.name for s in items_a} == {"A1", "A2"}
    assert {s.name for s in items_b} == {"B1"}


@pytest.mark.asyncio
async def test_update_scene(db_session):
    user_id = uuid.uuid4()
    scene = await service.create_scene(
        db_session,
        user_id=user_id,
        name="Untitled",
        manifest={"schema": 1, "name": "Untitled", "objects": []},
    )
    updated = await service.update_scene(
        db_session,
        scene,
        name="Renamed",
        manifest={"schema": 1, "name": "Renamed", "objects": [{"id": "1"}]},
    )
    assert updated.name == "Renamed"
    assert updated.manifest["objects"] == [{"id": "1"}]


async def _seed_default_scene(db_session, user_id):
    # The default scene is a normal row; create it with the reserved id so we
    # can assert the per-user endpoints refuse to touch it.
    scene = EditorScene(
        id=DEFAULT_SCENE_ID,
        user_id=user_id,
        name="Default",
        manifest={"schema": 1, "name": "Default", "objects": []},
    )
    db_session.add(scene)
    await db_session.flush()
    await db_session.commit()
    return scene


@pytest.mark.asyncio
async def test_default_scene_excluded_from_user_list(db_session):
    owner = uuid.uuid4()
    await _seed_default_scene(db_session, owner)
    await service.create_scene(db_session, user_id=owner, name="Mine", manifest={})
    items = await service.list_scenes_for_user(db_session, owner)
    # Even though `owner` is the row's user_id, the curated default must not
    # appear in their editable scene list.
    assert {s.name for s in items} == {"Mine"}


@pytest.mark.asyncio
async def test_default_scene_not_fetchable_by_owner(db_session):
    owner = uuid.uuid4()
    await _seed_default_scene(db_session, owner)
    # The owner cannot load it by id through the per-user lookup — this also
    # gates update/delete, so the shared template can't be overwritten.
    assert await service.get_scene_for_user(db_session, owner, DEFAULT_SCENE_ID) is None


@pytest.mark.asyncio
async def test_delete_scene(db_session):
    user_id = uuid.uuid4()
    scene = await service.create_scene(
        db_session, user_id=user_id, name="X", manifest={}
    )
    await service.delete_scene(db_session, scene)
    assert await service.get_scene_for_user(db_session, user_id, scene.id) is None
