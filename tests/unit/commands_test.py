from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.commands as commands
import app.packets
import app.settings
import app.state.services
import app.state.sessions
from app.commands import Context
from app.commands import ParsingError
from app.commands import parse__with__command_args
from app.commands import process_commands
from app.commands import recalc
from app.commands import status_to_id
from app.constants.gamemodes import GameMode
from app.constants.mods import Mods
from app.constants.privileges import Privileges
from app.objects.channel import Channel
from app.objects.collections import Channels
from app.objects.collections import Matches
from app.objects.collections import Players
from app.objects.match import Match
from app.objects.match import MatchTeamTypes
from app.objects.match import MatchWinConditions
from app.objects.match import SlotStatus
from app.objects.player import Player


class _RecordingPlayer(Player):
    def __init__(
        self,
        *,
        id: int,
        name: str,
        priv: Privileges,
    ) -> None:
        super().__init__(
            id=id,
            name=name,
            priv=priv,
            pw_bcrypt=None,
            token=Player.generate_token(),
        )
        self.restriction: tuple[Player, str] | None = None
        self.logged_out = False

    async def restrict(self, admin: Player, reason: str) -> None:
        self.restriction = (admin, reason)
        self.priv &= ~Privileges.UNRESTRICTED

    def logout(self) -> None:
        self.logged_out = True


def _player(*, id: int, name: str, priv: Privileges) -> Player:
    return Player(
        id=id,
        name=name,
        priv=priv,
        pw_bcrypt=None,
        token=Player.generate_token(),
    )


def _match(*, host: Player, guest: Player | None = None) -> Match:
    chat = Channel("#multi_0", "test match", instance=True)
    match = Match(
        id=0,
        name="test match",
        password="",
        has_public_history=True,
        map_name="Artist - Title [Difficulty]",
        map_id=123,
        map_md5="0123456789abcdef0123456789abcdef",
        host_id=host.id,
        mode=GameMode.VANILLA_OSU,
        mods=Mods.NOMOD,
        win_condition=MatchWinConditions.score,
        team_type=MatchTeamTypes.head_to_head,
        freemods=False,
        seed=0,
        chat_channel=chat,
    )
    match.slots[0].player = host
    match.slots[0].status = SlotStatus.playing
    chat.append(host)
    host.match = match
    if guest is not None:
        match.slots[1].player = guest
        match.slots[1].status = SlotStatus.playing
        chat.append(guest)
        guest.match = match
    return match


def test_with_command_arg_parser_accepts_acc_misses_combo_and_mods() -> None:
    parsed = parse__with__command_args(0, ["95.5%", "1m", "429x", "+hddt"])

    assert parsed == {
        "acc": 95.5,
        "mods": Mods.HIDDEN | Mods.DOUBLETIME,
        "combo": 429,
        "nmiss": 1,
    }


@pytest.mark.parametrize(
    ("args", "expected_error"),
    [
        ([], "Invalid syntax: !with <acc/nmiss/combo/mods ...>"),
        (["101%"], "Invalid accuracy."),
        (["bad"], "Unknown argument: bad"),
    ],
)
def test_with_command_arg_parser_rejects_invalid_args(
    args: list[str],
    expected_error: str,
) -> None:
    parsed = parse__with__command_args(0, args)

    assert isinstance(parsed, ParsingError)
    assert str(parsed) == expected_error


@pytest.mark.parametrize(
    ("status", "expected_id"),
    [
        ("unrank", 0),
        ("rank", 2),
        ("love", 5),
    ],
)
def test_status_to_id(status: str, expected_id: int) -> None:
    assert status_to_id(status) == expected_id


async def test_command_dispatch_requires_the_commands_privilege(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player = _player(
        id=3,
        name="ordinary player",
        priv=Privileges.UNRESTRICTED | Privileges.VERIFIED,
    )
    target = _RecordingPlayer(
        id=4,
        name="target",
        priv=Privileges.UNRESTRICTED | Privileges.VERIFIED,
    )
    players = Players()
    players.append(player)
    players.append(target)
    monkeypatch.setattr(app.state.sessions, "players", players)

    response = await process_commands(
        player,
        player,
        f"{app.settings.COMMAND_PREFIX}restrict target cc",
    )

    assert response is None
    assert target.restriction is None
    assert target.logged_out is False


async def test_recalc_updates_score_stats_and_leaderboards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beatmap = SimpleNamespace(id=315, md5="map-md5")
    player = _player(id=3, name="developer", priv=Privileges.DEVELOPER)
    player.last_np = {"bmap": beatmap}

    score = SimpleNamespace(
        id=42,
        userid=7,
        mode=0,
        mods=0,
        max_combo=100,
        ngeki=0,
        n300=300,
        nkatu=0,
        n100=0,
        n50=0,
        nmiss=0,
    )
    updated_scores: list[tuple[int, float]] = []
    updated_stats: list[tuple[int, int, int, float]] = []
    leaderboard_updates: list[tuple[str, dict[str, float]]] = []

    class FakeScores:
        async def fetch_many(self, **kwargs: object) -> list[object]:
            assert kwargs == {
                "map_md5": "map-md5",
                "status": commands.SubmissionStatus.BEST,
                "include_hidden_players": True,
            }
            return [score]

        async def partial_update(self, score_id: int, pp: float) -> None:
            updated_scores.append((score_id, pp))

        async def fetch_weighted_best_performances(
            self,
            *,
            user_id: int,
            mode: int,
        ) -> list[object]:
            assert (user_id, mode) == (7, 0)
            return [SimpleNamespace(pp=updated_scores[0][1], acc=98.0)]

    class FakeStats:
        async def partial_update(
            self,
            *,
            player_id: int,
            mode: int,
            pp: int,
            acc: float,
        ) -> None:
            updated_stats.append((player_id, mode, pp, acc))

    class FakeUsers:
        async def fetch_one(self, *, id: int) -> object:
            assert id == 7
            return SimpleNamespace(
                priv=Privileges.UNRESTRICTED,
                country="kr",
            )

    repos = SimpleNamespace(
        scores=FakeScores(),
        stats=FakeStats(),
        users=FakeUsers(),
    )

    class FakePerformanceService:
        def calculate_performances(
            self,
            *,
            osu_file_path: str,
            scores: list[commands.ScoreParams],
        ) -> list[object]:
            assert osu_file_path.endswith("/315.osu")
            assert scores[0].mode == 0
            return [SimpleNamespace(performance=SimpleNamespace(pp=10000.0))]

    async def ensure_osu_file_is_available(
        beatmap_id: int,
        expected_md5: str,
    ) -> bool:
        assert (beatmap_id, expected_md5) == (315, "map-md5")
        return True

    class FakeRedis:
        async def zadd(self, key: str, values: dict[str, float]) -> None:
            leaderboard_updates.append((key, values))

    monkeypatch.setattr(commands, "get_legacy_repositories", lambda: repos)
    monkeypatch.setattr(commands, "PerformanceService", FakePerformanceService)
    monkeypatch.setattr(
        commands,
        "ensure_osu_file_is_available",
        ensure_osu_file_is_available,
    )
    monkeypatch.setattr(app.state.sessions, "players", Players())
    monkeypatch.setattr(app.state.services, "redis", FakeRedis())

    response = await recalc(Context(player, "recalc", [], player))

    assert response == "Recalculated 1 best scores on beatmap 315."
    assert updated_scores == [(42, 9999.999)]
    assert updated_stats == [(7, 0, 10000, 98.0)]
    assert leaderboard_updates == [
        ("bancho:leaderboard:0", {"7": 10000}),
        ("bancho:leaderboard:0:kr", {"7": 10000}),
    ]


async def test_recalc_logs_request_before_validating_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player = _player(id=3, name="developer", priv=Privileges.DEVELOPER)
    log_messages: list[str] = []

    def capture_log(message: str, *args: object, **kwargs: object) -> None:
        log_messages.append(message)

    monkeypatch.setattr(commands, "log", capture_log)

    response = await recalc(Context(player, "recalc", ["not-a-map"], player))

    assert response == "Invalid syntax: !recalc [beatmap id]"
    assert log_messages[0].startswith(
        "In-game recalc requested by developer (id: 3)",
    )
    assert log_messages[1].startswith("Rejected recalc request from developer")


async def test_restrict_command_expands_reason_and_refreshes_online_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _player(
        id=3,
        name="admin",
        priv=(Privileges.UNRESTRICTED | Privileges.VERIFIED | Privileges.ADMINISTRATOR),
    )
    target = _RecordingPlayer(
        id=4,
        name="target",
        priv=Privileges.UNRESTRICTED | Privileges.VERIFIED,
    )
    players = Players()
    players.append(admin)
    players.append(target)
    monkeypatch.setattr(app.state.sessions, "players", players)

    response = await process_commands(
        admin,
        admin,
        f"{app.settings.COMMAND_PREFIX}restrict target cc",
    )

    assert response is not None
    assert response["resp"] is not None
    assert response["resp"] == "<target (4)> was restricted."
    assert response["hidden"] is True
    assert target.restriction == (admin, "using a modified osu! client")
    assert target.logged_out is True


async def test_multiplayer_abort_requires_a_referee_and_resets_match_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _player(
        id=3,
        name="host",
        priv=Privileges.UNRESTRICTED | Privileges.VERIFIED,
    )
    guest = _player(
        id=4,
        name="guest",
        priv=Privileges.UNRESTRICTED | Privileges.VERIFIED,
    )
    players = Players()
    players.append(host)
    players.append(guest)
    monkeypatch.setattr(app.state.sessions, "players", players)
    match = _match(host=host, guest=guest)
    match.in_progress = True
    for slot in match.slots[:2]:
        slot.loaded = True
        slot.skipped = True

    denied_response = await process_commands(
        guest,
        match.chat,
        f"{app.settings.COMMAND_PREFIX}mp abort",
    )

    assert denied_response == {"resp": None, "hidden": False}
    assert match.in_progress is True

    accepted_response = await process_commands(
        host,
        match.chat,
        f"{app.settings.COMMAND_PREFIX}mp abort",
    )

    assert accepted_response is not None
    assert accepted_response["resp"] is not None
    assert accepted_response["resp"] == "Match aborted."
    assert match.in_progress is False
    assert [slot.status for slot in match.slots[:2]] == [
        SlotStatus.not_ready,
        SlotStatus.not_ready,
    ]
    assert all(not slot.loaded and not slot.skipped for slot in match.slots)
    expected_packets = app.packets.match_abort() + app.packets.update_match(
        match,
        send_pw=True,
    )
    assert host.dequeue() == expected_packets
    assert guest.dequeue() == expected_packets


async def test_tournament_room_commands_create_manage_and_close_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creator = _player(
        id=3,
        name="creator",
        priv=Privileges.UNRESTRICTED | Privileges.VERIFIED,
    )
    guest = _player(
        id=4,
        name="guest",
        priv=Privileges.UNRESTRICTED | Privileges.VERIFIED,
    )
    spectator = _player(
        id=5,
        name="spectator",
        priv=Privileges.UNRESTRICTED | Privileges.VERIFIED,
    )
    bot = _player(
        id=1,
        name="BanchoBot",
        priv=Privileges.UNRESTRICTED,
    )
    players = Players()
    players.append(creator)
    players.append(guest)
    players.append(spectator)
    matches = Matches()
    channels = Channels()
    monkeypatch.setattr(app.state.sessions, "players", players)
    monkeypatch.setattr(app.state.sessions, "matches", matches)
    monkeypatch.setattr(app.state.sessions, "channels", channels)
    monkeypatch.setattr(app.state.sessions, "bot", bot, raising=False)

    created = await process_commands(
        creator,
        bot,
        f"{app.settings.COMMAND_PREFIX}mp make Test Tournament Room",
    )

    assert created is not None
    assert created["resp"] is not None
    match = creator.match
    assert match is not None
    assert match.tournament_room
    assert match.creator_id == creator.id
    assert match.has_public_history
    assert matches[match.id] is match

    assert guest.join_match(match, "")
    assert spectator.join_channel(match.chat)
    match.tourney_clients.add(spectator.id)

    renamed = await process_commands(
        creator,
        bot,
        f"{app.settings.COMMAND_PREFIX}mp {match.id} name Updated Tournament Room",
    )

    assert renamed == {"resp": "Match name updated.", "hidden": False}
    assert match.name == "Updated Tournament Room"

    creator.leave_match()
    assert creator.match is None
    assert matches[match.id] is match
    assert match.chat in channels

    closed = await process_commands(
        creator,
        bot,
        f"{app.settings.COMMAND_PREFIX}mp {match.id} close",
    )

    assert closed == {"resp": "Match closed.", "hidden": False}
    assert matches[match.id] is None
    assert creator.match is None
    assert guest.match is None
    assert spectator not in match.chat.players
    assert match.tourney_clients == set()
    assert all(slot.empty() for slot in match.slots)
    assert match.chat not in channels


async def test_invited_player_can_join_password_protected_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _player(
        id=3,
        name="host",
        priv=Privileges.UNRESTRICTED | Privileges.VERIFIED,
    )
    invitee = _player(
        id=4,
        name="invitee",
        priv=Privileges.UNRESTRICTED | Privileges.VERIFIED,
    )
    outsider = _player(
        id=5,
        name="outsider",
        priv=Privileges.UNRESTRICTED | Privileges.VERIFIED,
    )
    players = Players()
    for player in (host, invitee, outsider):
        players.append(player)

    match = _match(host)
    match.passwd = "secret"
    channels = Channels()
    channels.append(match.chat)
    monkeypatch.setattr(app.state.sessions, "players", players)
    monkeypatch.setattr(app.state.sessions, "channels", channels)

    response = await process_commands(
        host,
        match.chat,
        f"{app.settings.COMMAND_PREFIX}mp invite invitee",
    )

    assert response == {"resp": "Invited invitee to the match.", "hidden": False}
    assert not outsider.join_match(match, "")
    assert invitee.join_match(match, "")
    assert invitee.id not in match.invited_players
