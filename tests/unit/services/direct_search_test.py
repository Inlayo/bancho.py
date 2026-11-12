from __future__ import annotations

from datetime import datetime

import app.api.dependencies as api_dependencies
import app.services.direct_search as direct_search
import app.state.services
from app.repositories.maps import Map
from app.repositories.maps import MapServer


class _DirectSearchResponse:
    def __init__(
        self,
        *,
        status_code: int,
        payload: object,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self.text = text

    def json(self) -> object:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("Unexpected HTTP error.")


class _DirectSearchFetcher:
    def __init__(self, response: _DirectSearchResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, direct_search.DirectSearchParams]] = []

    async def __call__(
        self,
        url: str,
        *,
        params: direct_search.DirectSearchParams,
    ) -> _DirectSearchResponse:
        self.calls.append((url, params))
        return self.response


class _OsuApiV2SearchFetcher:
    def __init__(self, response: _DirectSearchResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, direct_search.OsuApiV2SearchParams, str, str]] = []

    async def __call__(
        self,
        url: str,
        *,
        params: direct_search.OsuApiV2SearchParams,
        client_id: str,
        client_secret: str,
    ) -> _DirectSearchResponse:
        self.calls.append((url, params, client_id, client_secret))
        return self.response


class _OldPpyMostPlayedFetcher:
    def __init__(self, response: _DirectSearchResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, int]] = []

    async def __call__(
        self,
        url: str,
        *,
        limit: int,
    ) -> _DirectSearchResponse:
        self.calls.append((url, limit))
        return self.response


class _MapsRepository:
    def __init__(self, maps: list[Map] | None = None) -> None:
        self.maps = maps or []
        self.calls: list[tuple[list[int], MapServer]] = []

    async def fetch_many_by_set_ids(
        self,
        set_ids: list[int],
        *,
        server: MapServer,
    ) -> list[Map]:
        self.calls.append((set_ids, server))
        return [
            beatmap
            for beatmap in self.maps
            if beatmap.set_id in set_ids and beatmap.server == server
        ]


def _map(
    *,
    id: int,
    set_id: int,
    status: int,
    mode: int = 0,
    version: str = "Hard",
) -> Map:
    return Map(
        id=id,
        server=MapServer.OSU,
        set_id=set_id,
        status=status,
        md5=f"{id:032}",
        artist="Artist",
        title="Title",
        version=version,
        creator="Creator",
        filename=f"{id}.osu",
        last_update=datetime(2024, 1, 1),
        total_length=120,
        max_combo=500,
        frozen=False,
        plays=0,
        passes=0,
        mode=mode,
        bpm=180.0,
        cs=4.0,
        ar=9.0,
        od=8.0,
        hp=6.0,
        diff=5.0,
    )


async def test_most_played_uses_old_ppy_and_akatsuki_map_statuses() -> None:
    old_ppy_fetcher = _OldPpyMostPlayedFetcher(
        _DirectSearchResponse(
            status_code=200,
            payload={},
            text=(
                '<a href="/s/101">First</a>'
                '<a href="/s/202">Second</a>'
                '<a href="/s/101">Duplicate</a>'
            ),
        ),
    )
    maps = _MapsRepository(
        [
            _map(id=1, set_id=101, status=2),
            _map(id=2, set_id=101, status=2, mode=3, version="Mania"),
            _map(id=3, set_id=202, status=5),
        ],
    )
    v2_fetcher = _OsuApiV2SearchFetcher(
        _DirectSearchResponse(status_code=503, payload={}),
    )
    mirror_fetcher = _DirectSearchFetcher(
        _DirectSearchResponse(status_code=503, payload=[]),
    )
    service = direct_search.DirectSearchService(
        maps=maps,
        osu_api_v2_client_id="123",
        osu_api_v2_client_secret="test-secret",
        osu_api_v2_search_endpoint="https://osu.ppy.sh/api/v2/beatmapsets/search",
        osu_api_v2_cursors={},
        fetch_osu_api_v2_search=v2_fetcher,
        old_ppy_most_played_endpoint=(direct_search.OLD_PPY_MOST_PLAYED_ENDPOINT),
        fetch_old_ppy_most_played=old_ppy_fetcher,
        mirror_search_endpoints=("https://mirror.test/search",),
        fetch_mirror_search=mirror_fetcher,
    )

    result = await service.search(
        ranked_status=0,
        query="Most Played",
        mode=0,
        page_num=0,
    )

    assert result.code is direct_search.DirectSearchResultCode.FOUND
    assert result.result_count == 1
    assert result.beatmap_sets is not None
    assert [beatmap_set.set_id for beatmap_set in result.beatmap_sets] == [101]
    assert result.beatmap_sets[0].ranked_status == 0
    assert [beatmap.name for beatmap in result.beatmap_sets[0].beatmaps] == [
        "Hard",
    ]
    assert old_ppy_fetcher.calls == [
        (direct_search.OLD_PPY_MOST_PLAYED_ENDPOINT, 25),
    ]
    assert maps.calls == [([101, 202], MapServer.OSU)]
    assert v2_fetcher.calls == []
    assert mirror_fetcher.calls == []


async def test_most_played_falls_back_when_old_ppy_is_unavailable() -> None:
    old_ppy_fetcher = _OldPpyMostPlayedFetcher(
        _DirectSearchResponse(status_code=403, payload={}),
    )
    v2_fetcher = _OsuApiV2SearchFetcher(
        _DirectSearchResponse(
            status_code=200,
            payload={
                "beatmapsets": [
                    {
                        "artist": "Artist",
                        "title": "Title",
                        "creator": "Creator",
                        "status": "ranked",
                        "last_updated": "2024-01-01T00:00:00Z",
                        "id": 123,
                        "video": False,
                        "beatmaps": [],
                    },
                ],
            },
        ),
    )
    service = direct_search.DirectSearchService(
        maps=_MapsRepository(),
        osu_api_v2_client_id="123",
        osu_api_v2_client_secret="test-secret",
        osu_api_v2_search_endpoint="https://osu.ppy.sh/api/v2/beatmapsets/search",
        osu_api_v2_cursors={},
        fetch_osu_api_v2_search=v2_fetcher,
        old_ppy_most_played_endpoint=(direct_search.OLD_PPY_MOST_PLAYED_ENDPOINT),
        fetch_old_ppy_most_played=old_ppy_fetcher,
        mirror_search_endpoints=("https://mirror.test/search",),
        fetch_mirror_search=_DirectSearchFetcher(
            _DirectSearchResponse(status_code=503, payload=[]),
        ),
    )

    result = await service.search(
        ranked_status=4,
        query="Most+Played",
        mode=-1,
        page_num=0,
    )

    assert result.code is direct_search.DirectSearchResultCode.FOUND
    assert result.beatmap_sets is not None
    assert result.beatmap_sets[0].set_id == 123
    assert old_ppy_fetcher.calls == [
        (direct_search.OLD_PPY_MOST_PLAYED_ENDPOINT, 25),
    ]
    assert v2_fetcher.calls[0][1] == {"sort": "plays_desc"}


async def test_direct_search_normalizes_mirror_response() -> None:
    response = _DirectSearchResponse(
        status_code=200,
        payload=[
            {
                "Artist": "A|rtist",
                "Title": "Title",
                "Creator": "Creator",
                "RankedStatus": 1,
                "LastUpdate": "2024-01-01",
                "SetID": 123,
                "HasVideo": True,
                "ChildrenBeatmaps": [
                    {
                        "DifficultyRating": 5.0,
                        "DiffName": "Hard|Pipe",
                        "CS": 4.0,
                        "OD": 8.0,
                        "AR": 9.0,
                        "HP": 6.5,
                        "Mode": 0,
                    },
                    {
                        "DifficultyRating": 2.5,
                        "DiffName": "Normal",
                        "CS": 3.0,
                        "OD": 6.0,
                        "AR": 7.0,
                        "HP": 4.5,
                        "Mode": 0,
                    },
                ],
            },
            {
                "Artist": "Skipped",
                "Title": "No children",
                "Creator": "Creator",
                "RankedStatus": 1,
                "LastUpdate": "2024-01-01",
                "SetID": 124,
                "HasVideo": False,
                "ChildrenBeatmaps": None,
            },
        ],
    )
    fetcher = _DirectSearchFetcher(response)
    v2_fetcher = _OsuApiV2SearchFetcher(
        _DirectSearchResponse(status_code=503, payload={}),
    )
    service = direct_search.DirectSearchService(
        maps=_MapsRepository(),
        osu_api_v2_client_id="123",
        osu_api_v2_client_secret="test-secret",
        osu_api_v2_search_endpoint="https://osu.ppy.sh/api/v2/beatmapsets/search",
        osu_api_v2_cursors={},
        fetch_osu_api_v2_search=v2_fetcher,
        old_ppy_most_played_endpoint=(direct_search.OLD_PPY_MOST_PLAYED_ENDPOINT),
        fetch_old_ppy_most_played=_OldPpyMostPlayedFetcher(
            _DirectSearchResponse(status_code=403, payload={}),
        ),
        mirror_search_endpoints=("https://mirror.test/search",),
        fetch_mirror_search=fetcher,
    )

    result = await service.search(
        ranked_status=0,
        query="camellia",
        mode=0,
        page_num=2,
    )

    assert result.code is direct_search.DirectSearchResultCode.FOUND
    assert result.result_count == 2
    assert v2_fetcher.calls == [
        (
            "https://osu.ppy.sh/api/v2/beatmapsets/search",
            {
                "q": "camellia",
                "m": 0,
                "s": "ranked",
                "sort": "relevance_desc",
            },
            "123",
            "test-secret",
        ),
    ]
    assert fetcher.calls == [
        (
            "https://mirror.test/search",
            {"amount": 100, "offset": 200, "query": "camellia", "mode": 0, "status": 1},
        ),
    ]
    assert result.beatmap_sets is not None
    assert len(result.beatmap_sets) == 1
    beatmap_set = result.beatmap_sets[0]
    assert beatmap_set.artist == "AIrtist"
    assert beatmap_set.has_video == 1
    assert [beatmap.name for beatmap in beatmap_set.beatmaps] == [
        "Normal",
        "HardIPipe",
    ]


async def test_direct_search_falls_back_to_next_mirror_when_empty() -> None:
    empty_response = _DirectSearchResponse(status_code=200, payload=[])
    result_response = _DirectSearchResponse(
        status_code=200,
        payload=[
            {
                "Artist": "Artist",
                "Title": "Title",
                "Creator": "Creator",
                "RankedStatus": 0,
                "LastUpdate": "2024-01-01",
                "SetID": 123,
                "HasVideo": 0,
                "ChildrenBeatmaps": [],
            },
        ],
    )

    class _FallbackFetcher:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def __call__(
            self,
            url: str,
            *,
            params: direct_search.DirectSearchParams,
        ) -> _DirectSearchResponse:
            self.calls.append(url)
            if url == "https://env.test/search":
                return _DirectSearchResponse(status_code=503, payload=[])
            if url == "https://catboy.best/api/search":
                return empty_response
            return result_response

    fetcher = _FallbackFetcher()
    v2_fetcher = _OsuApiV2SearchFetcher(
        _DirectSearchResponse(status_code=503, payload={}),
    )
    service = direct_search.DirectSearchService(
        maps=_MapsRepository(),
        osu_api_v2_client_id="123",
        osu_api_v2_client_secret="test-secret",
        osu_api_v2_search_endpoint="https://osu.ppy.sh/api/v2/beatmapsets/search",
        osu_api_v2_cursors={},
        fetch_osu_api_v2_search=v2_fetcher,
        old_ppy_most_played_endpoint=(direct_search.OLD_PPY_MOST_PLAYED_ENDPOINT),
        fetch_old_ppy_most_played=_OldPpyMostPlayedFetcher(
            _DirectSearchResponse(status_code=403, payload={}),
        ),
        mirror_search_endpoints=(
            "https://env.test/search",
            "https://catboy.best/api/search",
            "https://osu.direct/api/search",
        ),
        fetch_mirror_search=fetcher,
    )

    result = await service.search(
        ranked_status=4,
        query="camellia",
        mode=-1,
        page_num=0,
    )

    assert result.code is direct_search.DirectSearchResultCode.FOUND
    assert len(v2_fetcher.calls) == 1
    assert fetcher.calls == [
        "https://env.test/search",
        "https://catboy.best/api/search",
        "https://osu.direct/api/search",
    ]


async def test_direct_search_uses_osu_api_v2_first() -> None:
    v2_response = _DirectSearchResponse(
        status_code=200,
        payload={
            "beatmapsets": [
                {
                    "artist": "Artist",
                    "title": "Title",
                    "creator": "Creator",
                    "status": "ranked",
                    "last_updated": "2024-01-01T00:00:00Z",
                    "id": 123,
                    "video": True,
                    "beatmaps": [
                        {
                            "difficulty_rating": 5.0,
                            "version": "Hard",
                            "cs": 4.0,
                            "accuracy": 8.0,
                            "ar": 9.0,
                            "drain": 6.5,
                            "mode_int": 0,
                        },
                    ],
                },
            ],
            "cursor_string": "next-page",
        },
    )
    v2_fetcher = _OsuApiV2SearchFetcher(v2_response)
    mirror_fetcher = _DirectSearchFetcher(
        _DirectSearchResponse(status_code=503, payload=[]),
    )
    cursors: dict[tuple[str, int, int, str], dict[int, str]] = {}
    service = direct_search.DirectSearchService(
        maps=_MapsRepository(),
        osu_api_v2_client_id="123",
        osu_api_v2_client_secret="test-secret",
        osu_api_v2_search_endpoint="https://osu.ppy.sh/api/v2/beatmapsets/search",
        osu_api_v2_cursors=cursors,
        fetch_osu_api_v2_search=v2_fetcher,
        old_ppy_most_played_endpoint=(direct_search.OLD_PPY_MOST_PLAYED_ENDPOINT),
        fetch_old_ppy_most_played=_OldPpyMostPlayedFetcher(
            _DirectSearchResponse(status_code=403, payload={}),
        ),
        mirror_search_endpoints=("https://mirror.test/search",),
        fetch_mirror_search=mirror_fetcher,
    )

    result = await service.search(
        ranked_status=4,
        query="camellia",
        mode=0,
        page_num=0,
    )

    assert result.code is direct_search.DirectSearchResultCode.FOUND
    assert result.result_count == 1
    assert result.beatmap_sets is not None
    assert result.beatmap_sets[0].set_id == 123
    assert result.beatmap_sets[0].ranked_status == 0
    assert result.beatmap_sets[0].has_video == 1
    assert result.beatmap_sets[0].beatmaps[0].od == 8.0
    assert v2_fetcher.calls == [
        (
            "https://osu.ppy.sh/api/v2/beatmapsets/search",
            {"q": "camellia", "m": 0, "sort": "relevance_desc"},
            "123",
            "test-secret",
        ),
    ]
    assert cursors[("camellia", 4, 0, "relevance_desc")][1] == "next-page"
    assert mirror_fetcher.calls == []


async def test_direct_search_uses_osu_api_v2_cursor_for_next_page() -> None:
    class _CursorFetcher:
        def __init__(self) -> None:
            self.calls: list[direct_search.OsuApiV2SearchParams] = []

        async def __call__(
            self,
            url: str,
            *,
            params: direct_search.OsuApiV2SearchParams,
            client_id: str,
            client_secret: str,
        ) -> _DirectSearchResponse:
            self.calls.append(params.copy())
            if "cursor_string" not in params:
                return _DirectSearchResponse(
                    status_code=200,
                    payload={
                        "beatmapsets": [],
                        "cursor_string": "next-page",
                    },
                )
            return _DirectSearchResponse(
                status_code=200,
                payload={
                    "beatmapsets": [
                        {
                            "artist": "Artist",
                            "title": "Title",
                            "creator": "Creator",
                            "status": "loved",
                            "last_updated": "2024-01-01T00:00:00Z",
                            "id": 456,
                            "video": False,
                            "beatmaps": [],
                        },
                    ],
                },
            )

    fetcher = _CursorFetcher()
    service = direct_search.DirectSearchService(
        maps=_MapsRepository(),
        osu_api_v2_client_id="123",
        osu_api_v2_client_secret="test-secret",
        osu_api_v2_search_endpoint="https://osu.ppy.sh/api/v2/beatmapsets/search",
        osu_api_v2_cursors={},
        fetch_osu_api_v2_search=fetcher,
        old_ppy_most_played_endpoint=(direct_search.OLD_PPY_MOST_PLAYED_ENDPOINT),
        fetch_old_ppy_most_played=_OldPpyMostPlayedFetcher(
            _DirectSearchResponse(status_code=403, payload={}),
        ),
        mirror_search_endpoints=("https://mirror.test/search",),
        fetch_mirror_search=_DirectSearchFetcher(
            _DirectSearchResponse(status_code=503, payload=[]),
        ),
    )

    result = await service.search(
        ranked_status=4,
        query="camellia",
        mode=-1,
        page_num=1,
    )

    assert result.code is direct_search.DirectSearchResultCode.FOUND
    assert result.beatmap_sets is not None
    assert result.beatmap_sets[0].set_id == 456
    assert result.beatmap_sets[0].ranked_status == 8
    assert fetcher.calls == [
        {"q": "camellia", "sort": "relevance_desc"},
        {
            "q": "camellia",
            "sort": "relevance_desc",
            "cursor_string": "next-page",
        },
    ]


async def test_osu_api_v2_search_fetches_and_caches_oauth_token(
    monkeypatch,
) -> None:
    class _HTTPClient:
        def __init__(self) -> None:
            self.post_calls: list[tuple[str, dict[str, object], float]] = []
            self.get_calls: list[
                tuple[str, dict[str, object], dict[str, str], float]
            ] = []

        async def post(
            self,
            url: str,
            *,
            json: dict[str, object],
            timeout: float,
        ) -> _DirectSearchResponse:
            self.post_calls.append((url, json, timeout))
            return _DirectSearchResponse(
                status_code=200,
                payload={"access_token": "oauth-access-token", "expires_in": 3600},
            )

        async def get(
            self,
            url: str,
            *,
            params: dict[str, object],
            headers: dict[str, str],
            timeout: float,
        ) -> _DirectSearchResponse:
            self.get_calls.append((url, params, headers, timeout))
            return _DirectSearchResponse(status_code=200, payload=[])

    client = _HTTPClient()
    monkeypatch.setattr(app.state.services, "http_client", client)
    monkeypatch.setattr(app.state.cache, "osu_api_v2_access_token", None)
    monkeypatch.setattr(app.state.cache, "osu_api_v2_token_expires_at", 0.0)

    for _ in range(2):
        await api_dependencies._fetch_osu_api_v2_search(
            "https://osu.ppy.sh/api/v2/beatmapsets/search",
            params={"q": "camellia", "sort": "relevance_desc"},
            client_id="123",
            client_secret="oauth-client-secret",
        )

    assert client.post_calls == [
        (
            "https://osu.ppy.sh/oauth/token",
            {
                "client_id": 123,
                "client_secret": "oauth-client-secret",
                "grant_type": "client_credentials",
                "scope": "public",
            },
            5.0,
        ),
    ]
    assert (
        client.get_calls
        == [
            (
                "https://osu.ppy.sh/api/v2/beatmapsets/search",
                {"q": "camellia", "sort": "relevance_desc"},
                {"Authorization": "Bearer oauth-access-token"},
                2.0,
            ),
        ]
        * 2
    )


async def test_old_ppy_most_played_fetches_with_limit_form_data(
    monkeypatch,
) -> None:
    response = _DirectSearchResponse(status_code=200, payload={}, text="<html>")

    class _HTTPClient:
        def __init__(self) -> None:
            self.post_calls: list[tuple[str, dict[str, int], float]] = []

        async def post(
            self,
            url: str,
            *,
            data: dict[str, int],
            timeout: float,
        ) -> _DirectSearchResponse:
            self.post_calls.append((url, data, timeout))
            return response

    client = _HTTPClient()
    monkeypatch.setattr(app.state.services, "http_client", client)

    result = await api_dependencies._fetch_old_ppy_most_played(
        direct_search.OLD_PPY_MOST_PLAYED_ENDPOINT,
        limit=25,
    )

    assert result is response
    assert client.post_calls == [
        (direct_search.OLD_PPY_MOST_PLAYED_ENDPOINT, {"limit": 25}, 2.0),
    ]
