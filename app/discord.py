"""Functionality related to Discord interactivity."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC
from datetime import datetime
from typing import Any
from typing import Literal

from tenacity import retry
from tenacity import stop_after_attempt
from tenacity import wait_exponential

from app import settings
from app.logging import Ansi
from app.logging import log
from app.state import services

_SECRET_QUERY_PARAM = re.compile(r"(?i)([?&](?:token|code|secret|key)=)[^&\s]+")
_EMAIL_QUERY_PARAM = re.compile(r"(?i)([?&]email=)[^&\s]+")
_LONG_SECRET = re.compile(r"(?<![A-Za-z0-9])[\w-]{32,}(?![A-Za-z0-9])")
_STANDALONE_TOKEN = re.compile(r"(?m)^\s*[A-Za-z0-9_-]{8,}\s*$")
_AUDIT_FIELD_VALUE_LIMIT = 1024
_AUDIT_EMBED_VALUE_LIMIT = 6000
_AUDIT_EMBED_FIELD_LIMIT = 25


def _redact_audit_value(name: str, value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if not value.strip():
        return ""
    if name.casefold() == "recipient" and "@" in value:
        local_part, _, domain = value.rpartition("@")
        value = f"{local_part[:1]}***@{domain}"

    value = _SECRET_QUERY_PARAM.sub(r"\1[REDACTED]", value)
    value = _EMAIL_QUERY_PARAM.sub(r"\1[REDACTED]", value)
    if name.casefold() == "email_body":
        value = _LONG_SECRET.sub("[REDACTED]", value)
        value = _STANDALONE_TOKEN.sub("[REDACTED]", value)
    return value


def _split_audit_value(value: str) -> list[str]:
    parts: list[str] = []
    while len(value) > _AUDIT_FIELD_VALUE_LIMIT:
        split_at = value.rfind("\n", 0, _AUDIT_FIELD_VALUE_LIMIT + 1)
        if split_at < _AUDIT_FIELD_VALUE_LIMIT // 2:
            split_at = value.rfind(" ", 0, _AUDIT_FIELD_VALUE_LIMIT + 1)
        if split_at < _AUDIT_FIELD_VALUE_LIMIT // 2:
            split_at = _AUDIT_FIELD_VALUE_LIMIT

        parts.append(value[:split_at])
        value = value[split_at:]

    if value or not parts:
        parts.append(value)
    return parts


def format_audit_event(action: str, **fields: str) -> Embed:
    """Create a readable audit-log embed with safely redacted details."""
    normalized_action = action.casefold()
    if any(
        event in normalized_action
        for event in ("unrestricted", "unsilenced", "granted", "email sent")
    ):
        color = 0x57F287
    elif any(
        event in normalized_action
        for event in ("restricted", "silenced", "wiped", "failed", "removed")
    ):
        color = 0xED4245
    else:
        color = 0x5865F2

    title = action.strip()[:256] or "Audit Event"
    embed = Embed(
        title=title,
        color=color,
        timestamp=datetime.now(UTC).isoformat(),
    )
    footer = "bancho.py | Audit Log"
    embed.set_footer(text=footer)

    used_chars = len(title) + len(footer)
    for name, raw_value in fields.items():
        field_name = (
            name.replace("_", " ").title().replace(" Id", " ID").replace(" Url", " URL")
        )[:256]
        value = _redact_audit_value(name, raw_value) or "(none)"
        value_parts = _split_audit_value(value)

        for index, value_part in enumerate(value_parts, start=1):
            part_name = (
                f"{field_name} ({index}/{len(value_parts)})"
                if len(value_parts) > 1
                else field_name
            )[:256]
            remaining_chars = _AUDIT_EMBED_VALUE_LIMIT - used_chars - len(part_name)
            if len(embed.fields) >= _AUDIT_EMBED_FIELD_LIMIT or remaining_chars <= 0:
                return embed

            value_limit = min(_AUDIT_FIELD_VALUE_LIMIT, remaining_chars)
            if len(value_part) > value_limit:
                marker = "... (truncated)"
                if value_limit <= len(marker):
                    value_part = value_part[:value_limit]
                else:
                    value_part = (
                        value_part[: value_limit - len(marker)].rstrip() + marker
                    )

            embed.add_field(part_name, value_part, inline=False)
            used_chars += len(part_name) + len(value_part)

    return embed


class Footer:
    def __init__(self, text: str, **kwargs: Any) -> None:
        self.text = text
        self.icon_url = kwargs.get("icon_url")
        self.proxy_icon_url = kwargs.get("proxy_icon_url")


class Image:
    def __init__(self, **kwargs: Any) -> None:
        self.url = kwargs.get("url")
        self.proxy_url = kwargs.get("proxy_url")
        self.height = kwargs.get("height")
        self.width = kwargs.get("width")


class Thumbnail:
    def __init__(self, **kwargs: Any) -> None:
        self.url = kwargs.get("url")
        self.proxy_url = kwargs.get("proxy_url")
        self.height = kwargs.get("height")
        self.width = kwargs.get("width")


class Video:
    def __init__(self, **kwargs: Any) -> None:
        self.url = kwargs.get("url")
        self.height = kwargs.get("height")
        self.width = kwargs.get("width")


class Provider:
    def __init__(self, **kwargs: str) -> None:
        self.url = kwargs.get("url")
        self.name = kwargs.get("name")


class Author:
    def __init__(self, **kwargs: str) -> None:
        self.name = kwargs.get("name")
        self.url = kwargs.get("url")
        self.icon_url = kwargs.get("icon_url")
        self.proxy_icon_url = kwargs.get("proxy_icon_url")


class Field:
    def __init__(self, name: str, value: str, inline: bool = False) -> None:
        self.name = name
        self.value = value
        self.inline = inline


class Embed:
    def __init__(self, **kwargs: Any) -> None:
        self.title = kwargs.get("title")
        self.type = kwargs.get("type")
        self.description = kwargs.get("description")
        self.url = kwargs.get("url")
        self.timestamp = kwargs.get("timestamp")  # datetime
        self.color = kwargs.get("color", 0x000000)

        self.footer: Footer | None = kwargs.get("footer")
        self.image: Image | None = kwargs.get("image")
        self.thumbnail: Thumbnail | None = kwargs.get("thumbnail")
        self.video: Video | None = kwargs.get("video")
        self.provider: Provider | None = kwargs.get("provider")
        self.author: Author | None = kwargs.get("author")

        self.fields: list[Field] = kwargs.get("fields", [])

    def set_footer(self, **kwargs: Any) -> None:
        self.footer = Footer(**kwargs)

    def set_image(self, **kwargs: Any) -> None:
        self.image = Image(**kwargs)

    def set_thumbnail(self, **kwargs: Any) -> None:
        self.thumbnail = Thumbnail(**kwargs)

    def set_video(self, **kwargs: Any) -> None:
        self.video = Video(**kwargs)

    def set_provider(self, **kwargs: Any) -> None:
        self.provider = Provider(**kwargs)

    def set_author(self, **kwargs: Any) -> None:
        self.author = Author(**kwargs)

    def add_field(self, name: str, value: str, inline: bool = False) -> None:
        self.fields.append(Field(name, value, inline))


class Webhook:
    """A class to represent a single-use Discord webhook."""

    def __init__(self, url: str, **kwargs: Any) -> None:
        self.url = url
        self.content = kwargs.get("content")
        self.username = kwargs.get("username")
        self.avatar_url = kwargs.get("avatar_url")
        self.tts = kwargs.get("tts")
        self.file = kwargs.get("file")
        self.allowed_mentions = kwargs.get("allowed_mentions")
        self.embeds = kwargs.get("embeds", [])

    def add_embed(self, embed: Embed) -> None:
        self.embeds.append(embed)

    @property
    def json(self) -> Any:
        if not any([self.content, self.file, self.embeds]):
            raise Exception(
                "Webhook must contain at least one " "of (content, file, embeds).",
            )

        if self.content and len(self.content) > 2000:
            raise Exception("Webhook content must be under " "2000 characters.")

        payload: dict[str, Any] = {"embeds": []}

        for key in (
            "content",
            "username",
            "avatar_url",
            "tts",
            "file",
            "allowed_mentions",
        ):
            val = getattr(self, key)
            if val is not None:
                payload[key] = val

        for embed in self.embeds:
            embed_payload = {}

            # simple params
            for key in ("title", "type", "description", "url", "timestamp", "color"):
                val = getattr(embed, key)
                if val is not None:
                    embed_payload[key] = val

            # class params, must turn into dict
            for key in ("footer", "image", "thumbnail", "video", "provider", "author"):
                val = getattr(embed, key)
                if val is not None:
                    embed_payload[key] = val.__dict__

            if embed.fields:
                embed_payload["fields"] = [f.__dict__ for f in embed.fields]

            payload["embeds"].append(embed_payload)

        return payload

    @retry(
        stop=stop_after_attempt(10),
        wait=wait_exponential(multiplier=1, min=4, max=10),
    )
    async def post(self) -> None:
        """Post the webhook in JSON format."""
        # TODO: if `self.file is not None`, then we should
        #       use multipart/form-data instead of json payload.
        headers = {"Content-Type": "application/json"}
        response = await services.http_client.post(
            self.url,
            json=self.json,
            headers=headers,
        )
        response.raise_for_status()


def send_audit_log(
    embed: Embed,
    *,
    category: Literal["admin", "beatmap", "moderation", "email"] | None = None,
) -> None:
    """Post an audit event to its category webhook or the default webhook."""
    if category == "admin":
        category_webhook = settings.DISCORD_ADMIN_LOG_WEBHOOK
    elif category == "beatmap":
        category_webhook = settings.DISCORD_BEATMAP_LOG_WEBHOOK
    elif category == "moderation":
        category_webhook = settings.DISCORD_MODERATION_LOG_WEBHOOK
    elif category == "email":
        category_webhook = settings.DISCORD_EMAIL_LOG_WEBHOOK
    else:
        category_webhook = None
    webhook_url = category_webhook or settings.DISCORD_AUDIT_LOG_WEBHOOK
    if not webhook_url:
        return

    async def post_audit_log() -> None:
        try:
            webhook = Webhook(
                webhook_url,
                username="bancho.py",
                allowed_mentions={"parse": []},
            )
            webhook.add_embed(embed)
            await webhook.post()
        except Exception as exc:
            log(f"Failed to post Discord audit log: {exc}", Ansi.LRED)

    asyncio.create_task(post_audit_log())  # type: ignore[unused-awaitable]
