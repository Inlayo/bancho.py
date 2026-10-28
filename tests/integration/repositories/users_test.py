from __future__ import annotations

import secrets

import app.state.services
from app.constants.privileges import Privileges
from app.repositories.users import UsersRepository
from tests import factories


async def test_search_public_filters_to_verified_unrestricted_users() -> None:
    users = UsersRepository(app.state.services.database)
    suffix = secrets.token_hex(4)
    visible = await factories.create_user()
    unverified = await factories.create_user()
    restricted = await factories.create_user()

    await users.partial_update(
        id=visible.id,
        name=f"search-{suffix}-visible",
        priv=(Privileges.UNRESTRICTED | Privileges.VERIFIED).value,
    )
    await users.partial_update(
        id=unverified.id,
        name=f"search-{suffix}-unverified",
        priv=Privileges.UNRESTRICTED.value,
    )
    await users.partial_update(
        id=restricted.id,
        name=f"search-{suffix}-restricted",
        priv=Privileges.VERIFIED.value,
    )

    rows = await users.search_public(name=f"search-{suffix}")

    assert [(row.id, row.name) for row in rows] == [
        (visible.id, f"search-{suffix}-visible"),
    ]


async def test_user_search_matches_exact_id_before_name_matches() -> None:
    users = UsersRepository(app.state.services.database)
    target = await factories.create_user()
    name_match = await factories.create_user()
    updated_name_match = await users.partial_update(
        id=name_match.id,
        name=f"player-{target.id}-match",
    )
    assert updated_name_match is not None

    public_results = await users.search_public(name=str(target.id))
    assert public_results[0].id == target.id

    admin_results = await users.fetch_many(
        include_hidden=True,
        name=str(target.id),
    )
    assert admin_results[0].id == target.id
