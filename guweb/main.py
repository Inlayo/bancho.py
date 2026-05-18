#!/usr/bin/env python3.9

from __future__ import annotations

__all__ = ()

import os
from typing import Any

import aiohttp
import orjson
from cmyui.logging import Ansi
from cmyui.logging import log
from cmyui.mysql import AsyncSQLPool
from cmyui.version import Version
from objects import glob
from quart import Quart
from quart import render_template
from quart import session
from redis import asyncio as aioredis

app = Quart(__name__)
app.config["PERMANENT_SESSION_LIFETIME"] = 86300000

version = Version(1, 3, 0)

# used to secure session data.
# we recommend using a long randomly generated ascii string.
app.secret_key = glob.config.secret_key


@app.before_request
def make_session_permanent():
    session.permanent = True


@app.before_serving
async def mysql_conn() -> None:
    glob.db = AsyncSQLPool()
    await glob.db.connect(glob.config.mysql)
    log("Connected to MySQL!", Ansi.LGREEN)


@app.before_serving
async def redis_conn() -> None:
    glob.redis = await aioredis.from_url(glob.config.redisDSN)
    log("Connected to Redis!", Ansi.LGREEN)


@app.before_serving
async def http_conn() -> None:
    glob.http = aiohttp.ClientSession(json_serialize=lambda x: orjson.dumps(x).decode())
    log("Got our Client Session!", Ansi.LGREEN)


@app.after_serving
async def shutdown() -> None:
    await glob.db.close()
    await glob.redis.aclose()
    await glob.http.close()


# globals which can be used in template code
@app.template_global()
def appVersion() -> str:
    return str(version)


@app.template_global()
def appName() -> str:
    return str(glob.config.app_name)


@app.template_global()
def captchaKey() -> str:
    return str(glob.config.hCaptcha_sitekey)


@app.template_global()
def domain() -> str:
    return str(glob.config.domain)


from blueprints.frontend import frontend

app.register_blueprint(frontend)

from blueprints.admin import admin

app.register_blueprint(admin, url_prefix="/admin")


@app.errorhandler(404)
async def page_not_found(e: Exception) -> tuple[Any, int]:
    # NOTE: we set the 404 status explicitly
    return (await render_template("404.html"), 404)


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.realpath(__file__)))
    app.run(port=8590, debug=glob.config.debug)  # blocking call
