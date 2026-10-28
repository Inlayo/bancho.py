from __future__ import annotations

import pytest

import app.services.email_auth as email_auth
from app import settings


async def test_send_restriction_notice_includes_discord_appeal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[str, str, str]] = []

    async def capture_email(recipient: str, subject: str, body: str) -> None:
        sent.append((recipient, subject, body))

    monkeypatch.setattr(email_auth, "_send_email", capture_email)

    await email_auth.send_restriction_notice(
        "player@example.com",
        "test-player",
        "suspicious activity",
    )

    assert len(sent) == 1
    recipient, subject, body = sent[0]
    assert recipient == "player@example.com"
    assert subject == "Account restriction notice"
    assert "Hello test-player" in body
    assert "Reason: suspicious activity" in body
    assert f"Discord server at {settings.DISCORD_INVITE}" in body
    assert "contact the staff team to appeal" in body
