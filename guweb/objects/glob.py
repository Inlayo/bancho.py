from __future__ import annotations

__all__ = ("db", "http", "version", "cache")

from typing import TYPE_CHECKING
from typing import Any

import config  # imported for indirect use

if TYPE_CHECKING:
    from aiohttp import ClientSession
    from cmyui.mysql import AsyncSQLPool
    from cmyui.version import Version
    from redis.asyncio import Redis

db: AsyncSQLPool
redis: Redis[bytes]
http: ClientSession
version: Version

cache: dict[str, Any] = {"bcrypt": {}}
