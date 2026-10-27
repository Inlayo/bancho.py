# isort: dont-add-imports

from fastapi import APIRouter

from . import accounts
from . import admin
from . import chat
from . import clans
from . import leaderboards
from . import mail
from . import maps
from . import players
from . import scores
from . import server
from . import sessions

apiv2_router = APIRouter(tags=["API v2"], prefix="/v2")

apiv2_router.include_router(accounts.router)
apiv2_router.include_router(admin.router)
apiv2_router.include_router(chat.router)
apiv2_router.include_router(clans.router)
apiv2_router.include_router(leaderboards.router)
apiv2_router.include_router(mail.router)
apiv2_router.include_router(maps.router)
apiv2_router.include_router(players.router)
apiv2_router.include_router(scores.router)
apiv2_router.include_router(server.router)
apiv2_router.include_router(sessions.router)
