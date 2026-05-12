from __future__ import annotations

__all__ = ("db", "http", "version", "cache")

from typing import TYPE_CHECKING

import config  # imported for indirect use

if TYPE_CHECKING:
    from aiohttp import ClientSession
    from cmyui.mysql import AsyncSQLPool
    from cmyui.version import Version
    from redis import asyncio as aioredis

db: AsyncSQLPool
redis: aioredis
http: ClientSession
version: Version

cache = {"bcrypt": {}}
