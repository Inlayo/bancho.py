from __future__ import annotations

from collections.abc import Callable

import pytest

import app.services.email_auth as email_auth
from app import settings
from app.discord import Embed


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
    assert (subject, body) == email_auth.build_restriction_notice(
        "test-player",
        "suspicious activity",
    )


async def test_send_email_audits_recipient_subject_and_full_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 465)
    sent_messages = []
    audit_events: list[tuple[Embed, str]] = []

    class _FakeSMTP:
        def __enter__(self) -> _FakeSMTP:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def send_message(self, message: object) -> None:
            sent_messages.append(message)

    async def run_in_thread(
        func: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> None:
        func(*args, **kwargs)

    def capture_audit(embed: Embed, *, category: str) -> None:
        audit_events.append((embed, category))

    monkeypatch.setattr(email_auth.smtplib, "SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr(email_auth.asyncio, "to_thread", run_in_thread)
    monkeypatch.setattr(email_auth, "send_audit_log", capture_audit)

    await email_auth._send_email(
        "player@example.com",
        "Verify your email address",
        "Use token secret-token at https://example.com/register?token=secret-token",
    )

    assert len(sent_messages) == 1
    assert len(audit_events) == 1
    embed, category = audit_events[0]
    assert category == "email"
    assert embed.description == (
        "**Recipient:** player(at)example.com\n"
        "**Email Subject:** Verify your email address\n"
        "**Email Body:** Use token secret-token at "
        "https://example.com/register?token=secret-token"
    )
