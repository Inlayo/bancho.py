from __future__ import annotations

import asyncio

import pytest

import app.discord as discord


async def test_send_audit_log_posts_embed_without_mention_pings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discord.settings, "DISCORD_AUDIT_LOG_WEBHOOK", "webhook-url")
    posted: list[tuple[str, str, list[discord.Embed]]] = []
    posted_event = asyncio.Event()

    class _FakeWebhook:
        def __init__(self, url: str, *, username: str) -> None:
            self.url = url
            self.username = username
            self.embeds: list[discord.Embed] = []

        def add_embed(self, embed: discord.Embed) -> None:
            self.embeds.append(embed)

        async def post(self) -> None:
            posted.append((self.url, self.username, self.embeds))
            posted_event.set()

    monkeypatch.setattr(discord, "Webhook", _FakeWebhook)

    discord.send_audit_log(
        discord.format_audit_event(
            "Player restricted",
            target="@everyone (id: 42)",
        ),
    )
    await asyncio.wait_for(posted_event.wait(), timeout=1)

    assert len(posted) == 1
    url, username, embeds = posted[0]
    assert url == "webhook-url"
    assert username == "bancho.py"
    assert len(embeds) == 1
    assert embeds[0].title == "Player restricted"
    assert embeds[0].description == "**Target:** (at)everyone (id: 42)"
    assert embeds[0].color == 0xED4245
    assert embeds[0].footer is not None
    assert embeds[0].footer.text == "bancho.py | Audit Log"


def test_format_audit_event_uses_consistent_labeled_fields() -> None:
    embed = discord.format_audit_event(
        "Privileges updated",
        actor="Inlayo (id: 3)",
        added_roles="Administrator",
    )

    assert embed.title == "Privileges updated"
    assert embed.description == (
        "**Actor:** Inlayo (id: 3)\n**Added Roles:** Administrator"
    )
    assert embed.color == 0x5865F2
