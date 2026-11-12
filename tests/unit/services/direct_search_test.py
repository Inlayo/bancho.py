from __future__ import annotations

import app.api.dependencies as api_dependencies
import app.state.services
import app.services.direct_search as direct_search


class _DirectSearchResponse:
    def __init__(
        self,
        *,
        status_code: int,
        payload: object,
    ) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self) -> object:
        return self.payload


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
        self.calls: list[tuple[str, direct_search.OsuApiV2SearchParams, str]] = []

    async def __call__(
        self,
        url: str,
        *,
        params: direct_search.OsuApiV2SearchParams,
        token: str,
    ) -> _DirectSearchResponse:
        self.calls.append((url, params, token))
        return self.response


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
        osu_api_v2_token="test-token",
        osu_api_v2_search_endpoint="https://osu.ppy.sh/api/v2/beatmapsets/search",
        osu_api_v2_cursors={},
        fetch_osu_api_v2_search=v2_fetcher,
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
            "test-token",
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
        osu_api_v2_token="test-token",
        osu_api_v2_search_endpoint="https://osu.ppy.sh/api/v2/beatmapsets/search",
        osu_api_v2_cursors={},
        fetch_osu_api_v2_search=v2_fetcher,
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
        osu_api_v2_token="configured-token",
        osu_api_v2_search_endpoint="https://osu.ppy.sh/api/v2/beatmapsets/search",
        osu_api_v2_cursors=cursors,
        fetch_osu_api_v2_search=v2_fetcher,
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
            "configured-token",
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
            token: str,
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
        osu_api_v2_token="configured-token",
        osu_api_v2_search_endpoint="https://osu.ppy.sh/api/v2/beatmapsets/search",
        osu_api_v2_cursors={},
        fetch_osu_api_v2_search=fetcher,
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


async def test_osu_api_v2_search_sends_bearer_token(monkeypatch) -> None:
    class _HTTPClient:
        def __init__(self) -> None:
            self.call: tuple[str, dict[str, object], dict[str, str], float] | None = (
                None
            )

        async def get(
            self,
            url: str,
            *,
            params: dict[str, str | int],
            headers: dict[str, str],
            timeout: float,
        ) -> _DirectSearchResponse:
            self.call = (url, params, headers, timeout)
            return _DirectSearchResponse(status_code=200, payload={})

    client = _HTTPClient()
    monkeypatch.setattr(app.state.services, "http_client", client)

    await api_dependencies._fetch_osu_api_v2_search(
        "https://osu.ppy.sh/api/v2/beatmapsets/search",
        params={"q": "camellia", "sort": "relevance_desc"},
        token="oauth-access-token",
    )

    assert client.call == (
        "https://osu.ppy.sh/api/v2/beatmapsets/search",
        {"q": "camellia", "sort": "relevance_desc"},
        {"Authorization": "Bearer oauth-access-token"},
        2.0,
    )
