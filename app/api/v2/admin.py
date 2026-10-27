from __future__ import annotations

from typing import Annotated
from typing import Literal

from fastapi import APIRouter
from fastapi import Depends
from fastapi import status
from fastapi.param_functions import Query
from pydantic import BaseModel
from pydantic import Field

import app.state
import app.state.cache
from app.api import dependencies as api_dependencies
from app.api.v2.common import actors
from app.api.v2.common import responses
from app.api.v2.common.responses import Failure
from app.api.v2.common.responses import Success
from app.constants.beatmap_statuses import RankedStatus
from app.constants.gamemodes import GameMode
from app.constants.privileges import Privileges
from app.objects.player import Player
from app.repositories.map_requests import MapRequestsRepository
from app.repositories.maps import MapsRepository
from app.repositories.scores import ScoresRepository
from app.repositories.stats import StatsRepository
from app.repositories.users import User
from app.repositories.users import UsersRepository

router = APIRouter()

MANAGED_ROLE_PRIVILEGES = (
    Privileges.WHITELISTED
    | Privileges.SUPPORTER
    | Privileges.PREMIUM
    | Privileges.ALUMNI
    | Privileges.TOURNEY_MANAGER
    | Privileges.NOMINATOR
    | Privileges.MODERATOR
    | Privileges.ADMINISTRATOR
    | Privileges.DEVELOPER
)
BASE_PRIVILEGES = Privileges.UNRESTRICTED | Privileges.VERIFIED


class UpdatePrivilegesRequest(BaseModel):
    privileges: int = Field(ge=0)


class RestrictionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class WipeScoresRequest(BaseModel):
    mode: int | None = None


class UpdateMapStatusRequest(BaseModel):
    status: int
    scope: Literal["map", "set"] = "map"


def _require_admin(actor: User | None) -> Failure | None:
    if actor is None:
        return responses.failure(
            message="Authentication required.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    if not actor.priv & (Privileges.ADMINISTRATOR.value | Privileges.DEVELOPER.value):
        return responses.failure(
            message="Administrator access required.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return None


async def _load_target_player(user_id: int) -> Player | None:
    return await app.state.sessions.players.from_cache_or_sql(id=user_id)


def _can_manage_target(actor: User, target_privileges: int) -> bool:
    return (
        actor.priv & Privileges.DEVELOPER.value != 0
        or target_privileges & int(Privileges.STAFF) == 0
    )


@router.get("/admin/users")
async def search_admin_users(
    *,
    query: str = Query(..., min_length=2, max_length=32),
    actor: Annotated[
        User | None,
        Depends(actors.get_optional_actor),
    ],
    users: Annotated[
        UsersRepository,
        Depends(api_dependencies.get_users_repository),
    ],
) -> Success[list[dict[str, int | str]]] | Failure:
    denied = _require_admin(actor)
    if denied is not None:
        return denied

    users_found = await users.fetch_many(
        name=query,
        page=1,
        page_size=25,
        include_hidden=True,
    )
    return responses.success(
        [{"id": user.id, "name": user.name, "priv": user.priv} for user in users_found],
        meta={"total": len(users_found)},
    )


@router.get("/admin/users/{user_id}")
async def get_admin_user(
    user_id: int,
    *,
    actor: Annotated[
        User | None,
        Depends(actors.get_optional_actor),
    ],
    users: Annotated[
        UsersRepository,
        Depends(api_dependencies.get_users_repository),
    ],
    stats: Annotated[
        StatsRepository,
        Depends(api_dependencies.get_stats_repository),
    ],
) -> Success[dict[str, object]] | Failure:
    denied = _require_admin(actor)
    if denied is not None:
        return denied

    user = await users.fetch_one(id=user_id)
    if user is None:
        return responses.failure(
            message="Player not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    user_stats = await stats.fetch_many(player_id=user_id)
    return responses.success(
        {
            "id": user.id,
            "name": user.name,
            "priv": user.priv,
            "country": user.country,
            "creation_time": user.creation_time,
            "latest_activity": user.latest_activity,
            "stats": user_stats,
        },
    )


@router.patch("/admin/users/{user_id}/privileges")
async def update_admin_user_privileges(
    user_id: int,
    args: UpdatePrivilegesRequest,
    *,
    actor: Annotated[
        User | None,
        Depends(actors.get_optional_actor),
    ],
) -> Success[dict[str, int]] | Failure:
    denied = _require_admin(actor)
    if denied is not None:
        return denied
    assert actor is not None

    if args.privileges & ~int(MANAGED_ROLE_PRIVILEGES):
        return responses.failure(
            message="Invalid privilege bits.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if user_id == actor.id:
        return responses.failure(
            message="You cannot change your own privileges.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    target = await _load_target_player(user_id)
    if target is None or target.is_bot_client:
        return responses.failure(
            message="Player not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if not _can_manage_target(actor, int(target.priv)):
        return responses.failure(
            message="Only developers can manage staff accounts.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    new_roles = Privileges(args.privileges)
    if not actor.priv & Privileges.DEVELOPER.value and new_roles & Privileges.STAFF:
        return responses.failure(
            message="Only developers can grant staff privileges.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    new_privileges = (target.priv & ~MANAGED_ROLE_PRIVILEGES) | new_roles
    new_privileges = (new_privileges & ~BASE_PRIVILEGES) | (
        target.priv & BASE_PRIVILEGES
    )
    await target.update_privs(new_privileges)
    if target.is_online:
        import app.packets

        target.enqueue(app.packets.bancho_privileges(target.bancho_priv))

    return responses.success({"id": target.id, "priv": int(target.priv)})


@router.post("/admin/users/{user_id}/restrict")
async def restrict_admin_user(
    user_id: int,
    args: RestrictionRequest,
    *,
    actor: Annotated[
        User | None,
        Depends(actors.get_optional_actor),
    ],
) -> Success[dict[str, int | str]] | Failure:
    denied = _require_admin(actor)
    if denied is not None:
        return denied
    assert actor is not None

    if user_id == actor.id:
        return responses.failure(
            message="You cannot restrict your own account.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    target = await _load_target_player(user_id)
    if target is None or target.is_bot_client:
        return responses.failure(
            message="Player not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if not _can_manage_target(actor, int(target.priv)):
        return responses.failure(
            message="Only developers can manage staff accounts.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    if target.restricted:
        return responses.failure(
            message="Player is already restricted.",
            status_code=status.HTTP_409_CONFLICT,
        )

    admin = await _load_target_player(actor.id)
    if admin is None:
        return responses.failure(
            message="Administrator account could not be loaded.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    await target.restrict(admin=admin, reason=args.reason)
    return responses.success(
        {"id": target.id, "status": "restricted", "email_notice": "queued"},
    )


@router.post("/admin/users/{user_id}/unrestrict")
async def unrestrict_admin_user(
    user_id: int,
    args: RestrictionRequest,
    *,
    actor: Annotated[
        User | None,
        Depends(actors.get_optional_actor),
    ],
) -> Success[dict[str, int | str]] | Failure:
    denied = _require_admin(actor)
    if denied is not None:
        return denied
    assert actor is not None

    if user_id == actor.id:
        return responses.failure(
            message="You cannot change your own restriction status.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    target = await _load_target_player(user_id)
    if target is None or target.is_bot_client:
        return responses.failure(
            message="Player not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if not _can_manage_target(actor, int(target.priv)):
        return responses.failure(
            message="Only developers can manage staff accounts.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    if not target.restricted:
        return responses.failure(
            message="Player is not restricted.",
            status_code=status.HTTP_409_CONFLICT,
        )

    admin = await _load_target_player(actor.id)
    if admin is None:
        return responses.failure(
            message="Administrator account could not be loaded.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    await target.unrestrict(admin=admin, reason=args.reason)
    return responses.success({"id": target.id, "status": "unrestricted"})


@router.post("/admin/users/{user_id}/scores/wipe")
async def wipe_admin_user_scores(
    user_id: int,
    args: WipeScoresRequest,
    *,
    actor: Annotated[
        User | None,
        Depends(actors.get_optional_actor),
    ],
    users: Annotated[
        UsersRepository,
        Depends(api_dependencies.get_users_repository),
    ],
    scores: Annotated[
        ScoresRepository,
        Depends(api_dependencies.get_scores_repository),
    ],
    stats: Annotated[
        StatsRepository,
        Depends(api_dependencies.get_stats_repository),
    ],
) -> Success[dict[str, int | None]] | Failure:
    denied = _require_admin(actor)
    if denied is not None:
        return denied

    if args.mode is not None and args.mode not in {
        mode.value for mode in GameMode.valid_gamemodes()
    }:
        return responses.failure(
            message="Unsupported game mode.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    user = await users.fetch_one(id=user_id)
    target = await _load_target_player(user_id)
    if user is None or target is None or target.is_bot_client:
        return responses.failure(
            message="Player not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    assert actor is not None
    if not _can_manage_target(actor, int(target.priv)):
        return responses.failure(
            message="Only developers can manage staff accounts.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    modes = (
        [GameMode(args.mode)] if args.mode is not None else GameMode.valid_gamemodes()
    )
    async with app.state.services.database.transaction():
        score_ids = await scores.delete_user_scores(user_id, args.mode)
        for mode in modes:
            await stats.partial_update(
                player_id=user_id,
                mode=mode.value,
                tscore=0,
                rscore=0,
                pp=0,
                plays=0,
                playtime=0,
                acc=0.0,
                max_combo=0,
                total_hits=0,
                replay_views=0,
                xh_count=0,
                x_count=0,
                sh_count=0,
                s_count=0,
                a_count=0,
            )

    for mode in modes:
        await app.state.services.redis.zrem(
            f"bancho:leaderboard:{mode.value}",
            user_id,
        )
        await app.state.services.redis.zrem(
            f"bancho:leaderboard:{mode.value}:{target.geoloc['country']['acronym']}",
            user_id,
        )
        target.recent_scores[mode] = None
    await target.stats_from_sql_full()
    if target.is_online:
        import app.packets

        app.state.sessions.players.enqueue(app.packets.user_stats(target))

    return responses.success(
        {"id": user_id, "mode": args.mode, "deleted_scores": len(score_ids)},
    )


@router.get("/admin/maps/{map_id}")
async def get_admin_map(
    map_id: int,
    *,
    actor: Annotated[
        User | None,
        Depends(actors.get_optional_actor),
    ],
    maps: Annotated[
        MapsRepository,
        Depends(api_dependencies.get_maps_repository),
    ],
) -> Success[dict[str, int | str | bool]] | Failure:
    denied = _require_admin(actor)
    if denied is not None:
        return denied

    beatmap = await maps.fetch_one(id=map_id)
    if beatmap is None:
        return responses.failure(
            message="Beatmap not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return responses.success(
        {
            "id": beatmap.id,
            "set_id": beatmap.set_id,
            "artist": beatmap.artist,
            "title": beatmap.title,
            "version": beatmap.version,
            "creator": beatmap.creator,
            "status": beatmap.status,
            "frozen": beatmap.frozen,
        },
    )


@router.patch("/admin/maps/{map_id}/status")
async def update_admin_map_status(
    map_id: int,
    args: UpdateMapStatusRequest,
    *,
    actor: Annotated[
        User | None,
        Depends(actors.get_optional_actor),
    ],
    maps: Annotated[
        MapsRepository,
        Depends(api_dependencies.get_maps_repository),
    ],
    map_requests: Annotated[
        MapRequestsRepository,
        Depends(api_dependencies.get_map_requests_repository),
    ],
) -> Success[dict[str, int | str]] | Failure:
    denied = _require_admin(actor)
    if denied is not None:
        return denied

    try:
        new_status = RankedStatus(args.status)
    except ValueError:
        return responses.failure(
            message="Invalid beatmap status.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if new_status not in {
        RankedStatus.Pending,
        RankedStatus.Ranked,
        RankedStatus.Approved,
        RankedStatus.Qualified,
        RankedStatus.Loved,
    }:
        return responses.failure(
            message="This beatmap status cannot be set by administrators.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    beatmap = await maps.fetch_one(id=map_id)
    if beatmap is None:
        return responses.failure(
            message="Beatmap not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    updated_maps = (
        await maps.fetch_many(server=beatmap.server, set_id=beatmap.set_id)
        if args.scope == "set"
        else [beatmap]
    )

    async with app.state.services.database.transaction():
        for updated_map in updated_maps:
            await maps.partial_update(
                updated_map.id,
                status=int(new_status),
                frozen=True,
            )
        await map_requests.mark_batch_as_inactive(
            [updated_map.id for updated_map in updated_maps],
        )

    for updated_map in updated_maps:
        cached_map = app.state.cache.beatmap.get(updated_map.md5)
        if cached_map is not None:
            cached_map.status = new_status
            cached_map.frozen = True
    cached_set = app.state.cache.beatmapset.get(beatmap.set_id)
    if cached_set is not None and args.scope == "set":
        for cached_map in cached_set.maps:
            cached_map.status = new_status
            cached_map.frozen = True

    return responses.success(
        {
            "id": map_id,
            "status": int(new_status),
            "scope": args.scope,
        },
    )
