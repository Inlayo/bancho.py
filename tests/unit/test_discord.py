from __future__ import annotations

import asyncio

import pytest

import app.discord as discord


async def test_send_audit_log_posts_embed_without_mention_pings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discord.settings, "DISCORD_AUDIT_LOG_WEBHOOK", "webhook-url")
    posted: list[tuple[str, str, dict[str, list[str]], list[discord.Embed]]] = []
    posted_event = asyncio.Event()

    class _FakeWebhook:
        def __init__(
            self,
            url: str,
            *,
            username: str,
            allowed_mentions: dict[str, list[str]],
        ) -> None:
            self.url = url
            self.username = username
            self.allowed_mentions = allowed_mentions
            self.embeds: list[discord.Embed] = []

        def add_embed(self, embed: discord.Embed) -> None:
            self.embeds.append(embed)

        async def post(self) -> None:
            posted.append(
                (self.url, self.username, self.allowed_mentions, self.embeds),
            )
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
    url, username, allowed_mentions, embeds = posted[0]
    assert url == "webhook-url"
    assert username == "bancho.py"
    assert allowed_mentions == {"parse": []}
    assert len(embeds) == 1
    assert embeds[0].title == "Player restricted"
    assert [(field.name, field.value) for field in embeds[0].fields] == [
        ("Target", "@everyone (id: 42)"),
    ]
    assert embeds[0].color == 0xED4245
    assert embeds[0].footer is not None
    assert embeds[0].footer.text == "bancho.py | Audit Log"


async def test_send_audit_log_uses_category_webhook_or_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discord.settings, "DISCORD_AUDIT_LOG_WEBHOOK", "default-url")
    monkeypatch.setattr(discord.settings, "DISCORD_ADMIN_LOG_WEBHOOK", "")
    monkeypatch.setattr(discord.settings, "DISCORD_BEATMAP_LOG_WEBHOOK", "beatmap-url")
    monkeypatch.setattr(
        discord.settings,
        "DISCORD_MODERATION_LOG_WEBHOOK",
        "moderation-url",
    )
    monkeypatch.setattr(discord.settings, "DISCORD_EMAIL_LOG_WEBHOOK", "")
    posted: list[str] = []
    posted_event = asyncio.Event()

    class _FakeWebhook:
        def __init__(self, url: str, **kwargs: object) -> None:
            self.url = url

        def add_embed(self, embed: discord.Embed) -> None:
            pass

        async def post(self) -> None:
            posted.append(self.url)
            if len(posted) == 4:
                posted_event.set()

    monkeypatch.setattr(discord, "Webhook", _FakeWebhook)

    embed = discord.format_audit_event("Audit event")
    discord.send_audit_log(embed, category="beatmap")
    discord.send_audit_log(embed, category="moderation")
    discord.send_audit_log(embed, category="email")
    discord.send_audit_log(embed, category="admin")
    await asyncio.wait_for(posted_event.wait(), timeout=1)

    assert posted == [
        "beatmap-url",
        "moderation-url",
        "default-url",
        "default-url",
    ]


def test_format_audit_event_uses_consistent_labeled_fields() -> None:
    embed = discord.format_audit_event(
        "Privileges updated",
        actor="Inlayo (id: 3)",
        added_roles="Administrator",
    )

    assert embed.title == "Privileges updated"
    assert [(field.name, field.value) for field in embed.fields] == [
        ("Actor", "Inlayo (id: 3)"),
        ("Added Roles", "Administrator"),
    ]
    assert embed.color == 0x5865F2


def test_format_audit_event_preserves_email_layout_and_redacts_secrets() -> None:
    token = "secret-token"
    embed = discord.format_audit_event(
        "Email sent",
        recipient="player@example.com",
        email_subject="Verify your email address",
        email_body=(
            "Use this token:\n\n"
            f"{token}\n\n"
            "Open https://example.com/verify?token=secret-token"
            "&email=player%40example.com"
        ),
    )

    assert [(field.name, field.value) for field in embed.fields] == [
        ("Recipient", "p***@example.com"),
        ("Email Subject", "Verify your email address"),
        (
            "Email Body",
            "Use this token:\n\n"
            "[REDACTED]\n\n"
            "Open https://example.com/verify?token=[REDACTED]"
            "&email=[REDACTED]",
        ),
    ]


def test_format_audit_event_splits_long_values_without_losing_content() -> None:
    content = "line\n" * 300

    embed = discord.format_audit_event("Long audit event", email_body=content)

    assert [field.name for field in embed.fields] == [
        "Email Body (1/2)",
        "Email Body (2/2)",
    ]
    assert "".join(field.value for field in embed.fields) == content
