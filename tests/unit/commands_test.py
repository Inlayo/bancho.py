from __future__ import annotations

import pytest

import app.packets
import app.settings
import app.state.sessions
from app.commands import ParsingError
from app.commands import parse__with__command_args
from app.commands import process_commands
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
    bot = _player(
        id=1,
        name="BanchoBot",
        priv=Privileges.UNRESTRICTED,
    )
    players = Players()
    players.append(creator)
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
