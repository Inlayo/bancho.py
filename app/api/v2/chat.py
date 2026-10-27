"""bancho.py's v2 apis for public chat channels."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated
from typing import BinaryIO
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi import status

import app.packets
import app.state
from app.api import dependencies as api_dependencies
from app.api.v2.common import actors
from app.api.v2.common import responses
from app.api.v2.common.responses import Failure
from app.api.v2.common.responses import Success
from app.api.v2.models import BaseModel
from app.constants.privileges import Privileges
from app.logging import get_timestamp
from app.repositories.channels import ChannelsRepository
from app.repositories.users import User

router = APIRouter()

CHANNEL_LOG_RE = re.compile(
    r"^\[(?P<time>[^\]]+)\]\s+(?P<author>.+?)\s+@\s+(?P<channel>#[^:]+):\s*(?P<message>.*)$",
)


class ChatChannel(BaseModel):
    id: int
    name: str
    topic: str
    read_priv: int
    write_priv: int
    auto_join: bool


class ChatMessage(BaseModel):
    id: int
    channel: str
    author: str
    text: str
    time: str


class SendChatMessageRequest(BaseModel):
    message: str


def _read_channel_log_messages(
    channel_name: str,
    limit: int = 100,
) -> list[ChatMessage]:
    log_path = Path.cwd() / ".data" / "logs" / "chat.log"
    if not log_path.exists():
        return []

    items: list[ChatMessage] = []
    with log_path.open("rb") as handle:
        for offset, line in _iter_log_lines_reverse(handle):
            match = CHANNEL_LOG_RE.match(line.strip())
            if match is None or match.group("channel") != channel_name:
                continue

            items.append(
                ChatMessage(
                    id=offset,
                    channel=match.group("channel"),
                    author=match.group("author"),
                    text=match.group("message"),
                    time=match.group("time"),
                ),
            )
            if len(items) >= limit:
                break

    return list(reversed(items))


def _iter_log_lines_reverse(handle: BinaryIO) -> Iterator[tuple[int, str]]:
    position = handle.seek(0, 2)
    pending = b""

    while position > 0:
        chunk_size = min(8192, position)
        position -= chunk_size
        handle.seek(position)
        data = handle.read(chunk_size) + pending
        lines = data.split(b"\n")
        pending = lines[0]

        line_end = position + len(data)
        for line in reversed(lines[1:]):
            if line:
                line_end -= len(line)
                yield line_end, line.decode("utf-8")
            line_end -= 1

    if pending:
        yield 0, pending.decode("utf-8")


@router.post("/chat/channels/{channel_name}/messages")
async def send_chat_channel_message(
    channel_name: str,
    payload: SendChatMessageRequest,
    *,
    actor: Annotated[
        User | None,
        Depends(actors.get_optional_actor),
    ],
    channels_repository: Annotated[
        ChannelsRepository,
        Depends(api_dependencies.get_channels_repository),
    ],
) -> Success[ChatMessage] | Failure:
    if actor is None:
        return responses.failure(
            message="Authentication required.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if actor.priv & Privileges.UNRESTRICTED.value == 0:
        return responses.failure(
            message="This account cannot send chat messages.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    message = payload.message.strip()
    if not message or len(message) > 500 or "\n" in message or "\r" in message:
        return responses.failure(
            message="Message must contain 1-500 characters on one line.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    configured_channel = await channels_repository.fetch_one(name=channel_name)
    if configured_channel is None:
        return responses.failure(
            message="Channel not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if configured_channel.read_priv and actor.priv & configured_channel.read_priv == 0:
        return responses.failure(
            message="You cannot read this channel.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    if (
        configured_channel.write_priv
        and actor.priv & configured_channel.write_priv == 0
    ):
        return responses.failure(
            message="You cannot write to this channel.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    channel = app.state.sessions.channels.get_by_name(channel_name)
    if channel is not None:
        packet = app.packets.send_message(
            sender=actor.name,
            msg=message,
            recipient=channel.name,
            sender_id=actor.id,
        )
        for recipient in channel.players:
            if actor.id not in recipient.blocks:
                recipient.enqueue(packet)

    log_path = Path.cwd() / ".data" / "logs" / "chat.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"[{get_timestamp(full=True, tz=ZoneInfo('GMT'))}] "
            f"{actor.name} @ {channel_name}: {message}\n",
        )

    return responses.success(
        ChatMessage(
            id=time.time_ns() // 1_000_000,
            channel=channel_name,
            author=actor.name,
            text=message,
            time=get_timestamp(full=True, tz=ZoneInfo("GMT")),
        ),
    )


@router.get("/chat/channels")
async def get_chat_channels(
    *,
    actor: Annotated[
        User | None,
        Depends(actors.get_optional_actor),
    ],
    channels_repository: Annotated[
        ChannelsRepository,
        Depends(api_dependencies.get_channels_repository),
    ],
) -> Success[list[ChatChannel]] | Failure:
    rows = await channels_repository.fetch_many()
    readable_rows = [
        row
        for row in rows
        if not row.read_priv or (actor is not None and actor.priv & row.read_priv != 0)
    ]
    readable_rows.sort(key=lambda channel: channel.id)
    return responses.success(
        [
            ChatChannel.model_validate(
                {
                    "id": row.id,
                    "name": row.name,
                    "topic": row.topic,
                    "read_priv": row.read_priv,
                    "write_priv": row.write_priv,
                    "auto_join": row.auto_join,
                },
            )
            for row in readable_rows
        ],
        meta={"total": len(readable_rows)},
    )


@router.get("/chat/channels/{channel_name}/messages")
async def get_chat_channel_messages(
    channel_name: str,
    *,
    actor: Annotated[
        User | None,
        Depends(actors.get_optional_actor),
    ],
    channels_repository: Annotated[
        ChannelsRepository,
        Depends(api_dependencies.get_channels_repository),
    ],
    limit: int = Query(100, ge=1, le=200),
) -> Success[list[ChatMessage]] | Failure:
    if not channel_name.startswith("#"):
        return responses.failure(
            message="Invalid channel name.",
            status_code=400,
        )

    if actor is None:
        return responses.failure(
            message="Authentication required.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    channel = await channels_repository.fetch_one(name=channel_name)
    if channel is None:
        return responses.failure(
            message="Channel not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if channel.read_priv and actor.priv & channel.read_priv == 0:
        return responses.failure(
            message="You cannot read this channel.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    messages = _read_channel_log_messages(channel_name, limit=limit)
    return responses.success(messages, meta={"channel": channel_name, "limit": limit})
