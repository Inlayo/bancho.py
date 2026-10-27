from __future__ import annotations

import asyncio

import pytest

import app.discord as discord


async def test_send_audit_log_posts_content_without_mention_pings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discord.settings, "DISCORD_AUDIT_LOG_WEBHOOK", "webhook-url")
    posted: list[tuple[str, str]] = []
    posted_event = asyncio.Event()

    class _FakeWebhook:
        def __init__(self, url: str, *, content: str) -> None:
            self.url = url
            self.content = content

        async def post(self) -> None:
            posted.append((self.url, self.content))
            posted_event.set()

    monkeypatch.setattr(discord, "Webhook", _FakeWebhook)

    discord.send_audit_log(
        discord.format_audit_event(
            "Player restricted",
            target="@everyone (id: 42)",
        ),
    )
    await asyncio.wait_for(posted_event.wait(), timeout=1)

    assert posted == [
        (
            "webhook-url",
            "Player restricted | Target: (at)everyone (id: 42)",
        ),
    ]


def test_format_audit_event_uses_consistent_labeled_fields() -> None:
    assert discord.format_audit_event(
        "Privileges updated",
        actor="Inlayo (id: 3)",
        added_roles="Administrator",
    ) == ("Privileges updated | Actor: Inlayo (id: 3) | " "Added Roles: Administrator")
