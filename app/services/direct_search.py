from __future__ import annotations

import re
from collections.abc import Awaitable
from collections.abc import MutableMapping
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
from typing import NotRequired
from typing import Protocol
from typing import TypedDict

import httpx

from app.constants.beatmap_statuses import RankedStatus
from app.repositories.maps import Map
from app.repositories.maps import MapServer

OLD_PPY_MOST_PLAYED_LIMIT = 100
OLD_PPY_MOST_PLAYED_ENDPOINT = "https://old.ppy.sh/pages/include/home-mostplayed.php"


class DirectSearchParams(TypedDict):
    amount: int
    offset: int
    query: NotRequired[str]
    mode: NotRequired[int]
    status: NotRequired[int]


class OsuApiV2SearchParams(TypedDict):
    q: NotRequired[str]
    m: NotRequired[int]
    s: NotRequired[str]
    sort: str
    cursor_string: NotRequired[str]


class DirectSearchBeatmapPayload(TypedDict):
    DifficultyRating: float
    DiffName: str
    CS: float
    OD: float
    AR: float
    HP: float
    Mode: int


class DirectSearchSetPayload(TypedDict):
    Artist: str
    Title: str
    Creator: str
    RankedStatus: int
    LastUpdate: str
    SetID: int
    HasVideo: bool | int
    ChildrenBeatmaps: list[DirectSearchBeatmapPayload] | None


class DirectSearchHTTPResponse(Protocol):
    status_code: int

    def json(self) -> object: ...


class DirectSearchGetter(Protocol):
    def __call__(
        self,
        url: str,
        *,
        params: DirectSearchParams,
    ) -> Awaitable[DirectSearchHTTPResponse]: ...


class OldPpyMostPlayedHTTPResponse(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...


class OldPpyMostPlayedGetter(Protocol):
    def __call__(
        self,
        url: str,
        *,
        limit: int,
    ) -> Awaitable[OldPpyMostPlayedHTTPResponse]: ...


class DirectSearchMapsRepository(Protocol):
    async def fetch_many_by_set_ids(
        self,
        set_ids: list[int],
        *,
        server: MapServer,
    ) -> list[Map]: ...


class OsuApiV2SearchGetter(Protocol):
    def __call__(
        self,
        url: str,
        *,
        params: OsuApiV2SearchParams,
        client_id: str,
        client_secret: str,
    ) -> Awaitable[DirectSearchHTTPResponse]: ...


@dataclass(frozen=True)
class DirectSearchBeatmap:
    difficulty_rating: float
    name: str
    cs: float
    od: float
    ar: float
    hp: float
    mode: int


@dataclass(frozen=True)
class DirectSearchSet:
    artist: str
    title: str
    creator: str
    ranked_status: int
    last_update: str
    set_id: int
    has_video: int
    beatmaps: list[DirectSearchBeatmap]


class DirectSearchResultCode(StrEnum):
    FOUND = "found"
    MIRROR_ERROR = "mirror_error"


@dataclass(frozen=True)
class DirectSearchResult:
    code: DirectSearchResultCode
    result_count: int = 0
    beatmap_sets: list[DirectSearchSet] | None = None


class _MostPlayedSetIdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.set_ids: list[int] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag != "a":
            return

        href = dict(attrs).get("href")
        if href is None:
            return

        match = re.fullmatch(r"/s/(\d+)", href)
        if match is None:
            return

        set_id = int(match.group(1))
        if set_id not in self.set_ids:
            self.set_ids.append(set_id)


@dataclass(frozen=True)
class DirectSearchService:
    maps: DirectSearchMapsRepository
    osu_api_v2_client_id: str | None
    osu_api_v2_client_secret: str | None
    osu_api_v2_search_endpoint: str
    osu_api_v2_cursors: MutableMapping[
        tuple[str, int, int, str],
        dict[int, str],
    ]
    fetch_osu_api_v2_search: OsuApiV2SearchGetter
    old_ppy_most_played_endpoint: str
    fetch_old_ppy_most_played: OldPpyMostPlayedGetter
    mirror_search_endpoints: Sequence[str]
    fetch_mirror_search: DirectSearchGetter

    async def search(
        self,
        *,
        ranked_status: int,
        query: str,
        mode: int,
        page_num: int,
    ) -> DirectSearchResult:
        offset = page_num * 100
        special_queries = {
            "Newest": ("updated_desc", None),
            "Top+Rated": ("rating_desc", None),
            "Most+Played": ("plays_desc", None),
            "Top Rated": ("rating_desc", None),
            "Most Played": ("plays_desc", None),
        }
        sort, search_query = special_queries.get(
            query,
            ("relevance_desc" if query else "ranked_desc", query or None),
        )
        search_status = {
            0: 1,
            1: 2,
            2: 0,
            3: 3,
            5: 0,
            6: 0,
            7: 1,
            8: 4,
        }.get(ranked_status)
        if query in {"Most+Played", "Most Played"}:
            old_ppy_result = await self._search_old_ppy_most_played(
                ranked_status=search_status,
                mode=mode,
                page_num=page_num,
            )
            if old_ppy_result is not None and old_ppy_result.beatmap_sets:
                return old_ppy_result

        if self.osu_api_v2_client_id and self.osu_api_v2_client_secret:
            osu_api_result = await self._search_osu_api_v2(
                ranked_status=ranked_status,
                query=search_query,
                mode=mode,
                sort=sort,
                page_num=page_num,
            )
            if osu_api_result is not None and osu_api_result.beatmap_sets:
                return osu_api_result

        params: DirectSearchParams = {
            "amount": 100,
            "offset": offset,
        }

        if search_query is not None:
            params["query"] = search_query

        if mode != -1:  # -1 for all
            params["mode"] = mode

        if search_status is not None:
            params["status"] = search_status

        succeeded_with_empty_results = False
        for endpoint in self.mirror_search_endpoints:
            try:
                response = await self.fetch_mirror_search(endpoint, params=params)
                if response.status_code != 200:
                    continue
                payload = response.json()
                if not isinstance(payload, list):
                    continue
                beatmap_sets = self._payload_to_sets(payload)
            except (httpx.HTTPError, KeyError, TypeError, ValueError):
                continue

            if beatmap_sets:
                result_count = len(payload)
                return DirectSearchResult(
                    code=DirectSearchResultCode.FOUND,
                    result_count=101 if result_count == 100 else result_count,
                    beatmap_sets=beatmap_sets,
                )
            succeeded_with_empty_results = True

        if succeeded_with_empty_results:
            return DirectSearchResult(
                code=DirectSearchResultCode.FOUND,
                beatmap_sets=[],
            )
        return DirectSearchResult(code=DirectSearchResultCode.MIRROR_ERROR)

    async def _search_old_ppy_most_played(
        self,
        *,
        ranked_status: int | None,
        mode: int,
        page_num: int,
    ) -> DirectSearchResult | None:
        if page_num != 0:
            return None

        try:
            response = await self.fetch_old_ppy_most_played(
                self.old_ppy_most_played_endpoint,
                limit=OLD_PPY_MOST_PLAYED_LIMIT,
            )
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None

        parser = _MostPlayedSetIdParser()
        parser.feed(response.text)
        if not parser.set_ids:
            return None

        maps = await self.maps.fetch_many_by_set_ids(
            parser.set_ids,
            server=MapServer.OSU,
        )
        maps_by_set_id: dict[int, list[Map]] = {}
        for beatmap in maps:
            maps_by_set_id.setdefault(beatmap.set_id, []).append(beatmap)

        beatmap_sets: list[DirectSearchSet] = []
        direct_status_by_api_status = {
            0: 2,
            1: 0,
            2: 1,
            3: 3,
            4: 8,
        }

        for set_id in parser.set_ids:
            set_maps = maps_by_set_id.get(set_id)
            if not set_maps:
                continue

            if mode != -1:
                set_maps = [beatmap for beatmap in set_maps if beatmap.mode == mode]
            if not set_maps:
                continue

            try:
                api_status = RankedStatus(set_maps[0].status).osu_api
            except (KeyError, ValueError):
                continue
            direct_status = direct_status_by_api_status[api_status]
            if ranked_status is not None and api_status != ranked_status:
                continue

            matching_maps: list[Map] = []
            for beatmap in set_maps:
                try:
                    beatmap_api_status = RankedStatus(beatmap.status).osu_api
                except (KeyError, ValueError):
                    continue
                if beatmap_api_status == api_status:
                    matching_maps.append(beatmap)
            if not matching_maps:
                continue

            first_map = matching_maps[0]
            beatmap_sets.append(
                DirectSearchSet(
                    artist=self._replace_osudirect_delimiter(first_map.artist),
                    title=self._replace_osudirect_delimiter(first_map.title),
                    creator=first_map.creator,
                    ranked_status=direct_status,
                    last_update=first_map.last_update.isoformat(sep=" "),
                    set_id=set_id,
                    has_video=0,
                    beatmaps=[
                        DirectSearchBeatmap(
                            difficulty_rating=beatmap.diff,
                            name=self._replace_osudirect_delimiter(
                                beatmap.version,
                            ),
                            cs=beatmap.cs,
                            od=beatmap.od,
                            ar=beatmap.ar,
                            hp=beatmap.hp,
                            mode=beatmap.mode,
                        )
                        for beatmap in sorted(
                            matching_maps,
                            key=lambda map: map.diff,
                        )
                    ],
                ),
            )

        if not beatmap_sets:
            return None

        return DirectSearchResult(
            code=DirectSearchResultCode.FOUND,
            result_count=len(beatmap_sets),
            beatmap_sets=beatmap_sets,
        )

    async def _search_osu_api_v2(
        self,
        *,
        ranked_status: int,
        query: str | None,
        mode: int,
        sort: str,
        page_num: int,
    ) -> DirectSearchResult | None:
        assert self.osu_api_v2_client_id is not None
        assert self.osu_api_v2_client_secret is not None
        if page_num < 0:
            return None

        cursor_key = (query or "", ranked_status, mode, sort)
        if page_num == 0:
            self.osu_api_v2_cursors.pop(cursor_key, None)

        params: OsuApiV2SearchParams = {"sort": sort}
        if query is not None:
            params["q"] = query
        if mode != -1:
            params["m"] = mode

        status_filter = {
            0: "ranked",
            1: "ranked",
            2: "pending",
            3: "qualified",
            5: "graveyard",
            6: "wip",
            7: "ranked",
            8: "loved",
        }.get(ranked_status)
        if status_filter is not None:
            params["s"] = status_filter

        raw_sets: list[object] = []
        for requested_page in range(page_num + 1):
            cached_cursors = self.osu_api_v2_cursors.get(cursor_key, {})
            if requested_page < page_num and requested_page + 1 in cached_cursors:
                continue
            cursor = cached_cursors.get(requested_page)
            if requested_page > 0 and cursor is None:
                return None
            if cursor is not None:
                params["cursor_string"] = cursor
            else:
                params.pop("cursor_string", None)

            try:
                response = await self.fetch_osu_api_v2_search(
                    self.osu_api_v2_search_endpoint,
                    params=params,
                    client_id=self.osu_api_v2_client_id,
                    client_secret=self.osu_api_v2_client_secret,
                )
                if response.status_code != 200:
                    return None
                payload = response.json()
                if not isinstance(payload, dict):
                    return None
                response_sets = payload.get("beatmapsets")
                if not isinstance(response_sets, list):
                    return None
                raw_sets = response_sets
                next_cursor = payload.get("cursor_string")
                if isinstance(next_cursor, str) and next_cursor:
                    if (
                        cursor_key not in self.osu_api_v2_cursors
                        and len(self.osu_api_v2_cursors) >= 256
                    ):
                        self.osu_api_v2_cursors.pop(
                            next(iter(self.osu_api_v2_cursors)),
                        )
                    cursors = self.osu_api_v2_cursors.setdefault(cursor_key, {})
                    cursors[requested_page + 1] = next_cursor
            except (
                httpx.HTTPError,
                KeyError,
                TypeError,
                ValueError,
            ):
                return None

        try:
            beatmap_sets = self._osu_api_v2_payload_to_sets(raw_sets)
        except (KeyError, TypeError, ValueError):
            return None

        return DirectSearchResult(
            code=DirectSearchResultCode.FOUND,
            result_count=101 if len(raw_sets) == 100 else len(raw_sets),
            beatmap_sets=beatmap_sets,
        )

    def _osu_api_v2_payload_to_sets(
        self,
        result: list[object],
    ) -> list[DirectSearchSet]:
        ranked_status_by_name = {
            "ranked": 0,
            "approved": 1,
            "pending": 2,
            "qualified": 3,
            "graveyard": 5,
            "wip": 6,
            "loved": 8,
        }
        beatmap_sets: list[DirectSearchSet] = []
        for payload in result:
            if not isinstance(payload, dict):
                raise TypeError("Expected osu! API v2 beatmapset object.")
            status_name = payload["status"]
            if not isinstance(status_name, str):
                raise TypeError("Expected beatmapset status to be a string.")
            raw_maps = payload["beatmaps"]
            if not isinstance(raw_maps, list):
                raise TypeError("Expected beatmaps to be a list.")

            sorted_maps = sorted(
                raw_maps,
                key=lambda beatmap: beatmap["difficulty_rating"],
            )
            beatmap_sets.append(
                DirectSearchSet(
                    artist=self._replace_osudirect_delimiter(payload["artist"]),
                    title=self._replace_osudirect_delimiter(payload["title"]),
                    creator=payload["creator"],
                    ranked_status=ranked_status_by_name.get(status_name, 2),
                    last_update=payload["last_updated"],
                    set_id=payload["id"],
                    has_video=int(payload["video"]),
                    beatmaps=[
                        DirectSearchBeatmap(
                            difficulty_rating=beatmap["difficulty_rating"],
                            name=self._replace_osudirect_delimiter(
                                beatmap["version"],
                            ),
                            cs=beatmap["cs"],
                            od=beatmap["accuracy"],
                            ar=beatmap["ar"],
                            hp=beatmap["drain"],
                            mode=beatmap["mode_int"],
                        )
                        for beatmap in sorted_maps
                    ],
                ),
            )
        return beatmap_sets

    def _payload_to_sets(
        self,
        result: list[DirectSearchSetPayload],
    ) -> list[DirectSearchSet]:
        beatmap_sets: list[DirectSearchSet] = []
        for bmapset in result:
            if bmapset["ChildrenBeatmaps"] is None:
                continue
            diff_sorted_maps = sorted(
                bmapset["ChildrenBeatmaps"],
                key=lambda beatmap: beatmap["DifficultyRating"],
            )
            beatmap_sets.append(
                DirectSearchSet(
                    artist=self._replace_osudirect_delimiter(bmapset["Artist"]),
                    title=self._replace_osudirect_delimiter(bmapset["Title"]),
                    creator=bmapset["Creator"],
                    ranked_status=bmapset["RankedStatus"],
                    last_update=bmapset["LastUpdate"],
                    set_id=bmapset["SetID"],
                    has_video=int(bmapset["HasVideo"]),
                    beatmaps=[
                        DirectSearchBeatmap(
                            difficulty_rating=beatmap["DifficultyRating"],
                            name=self._replace_osudirect_delimiter(
                                beatmap["DiffName"],
                            ),
                            cs=beatmap["CS"],
                            od=beatmap["OD"],
                            ar=beatmap["AR"],
                            hp=beatmap["HP"],
                            mode=beatmap["Mode"],
                        )
                        for beatmap in diff_sorted_maps
                    ],
                ),
            )
        return beatmap_sets

    def _replace_osudirect_delimiter(self, value: str) -> str:
        # XXX: this is a bug that exists on official servers (lmao)
        # | is used to delimit the set data, so the difficulty name
        # cannot contain this or it will be ignored. we fix it here
        # by using a different character.
        return value.replace("|", "I")
