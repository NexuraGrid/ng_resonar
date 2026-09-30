from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import deps
from .cache import make_cache
from .config import settings
from .db import dispose_engine, init_engine
from .deps import current_user, require_superadmin
from .origin_check import OriginCheckMiddleware
from .routers import (
    auth as auth_router,
    download,
    favorites as favorites_router,
    history as history_router,
    lyrics,
    playlists as playlists_router,
    recommendations as recs_router,
    search,
    settings as settings_router,
    sponsorblock,
    stream,
    users as users_router,
    video,
    videolib,
)
from .services import audiobatch
from .services.videolib import cleanup_partials


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_partials()
    audiobatch.cleanup_old()
    deps.cache = make_cache()
    deps.http = httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(connect=15.0, read=None, write=30.0, pool=15.0),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    init_engine()
    if settings.redis_url:
        deps.redis = aioredis.from_url(
            settings.redis_url, decode_responses=True
        )
    try:
        yield
    finally:
        await deps.http.aclose()
        if deps.redis is not None:
            await deps.redis.aclose()
        dispose_engine()


# Interactive docs and the OpenAPI schema are disabled: they sit outside the
# ``/api`` prefix and so bypass the router-level session guard, which would leave
# the whole route map readable on an otherwise fully-authenticated instance.
app = FastAPI(
    title="Resonar API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

app.add_middleware(OriginCheckMiddleware, allowed_origins=_cors_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Public shell: login / me / bootstrap are reachable with no session; logout and
# password change carry a route-level ``Depends(current_user)`` (see routers/auth.py).
app.include_router(auth_router.router, prefix="/api")

# Every other API surface requires a valid session. `current_user` is attached
# at router level so an unlisted-but-public route cannot become an auth bypass.
_guard = Depends(current_user)
for _router in (
    search,
    stream,
    video,
    videolib,
    sponsorblock,
    lyrics,
    playlists_router,
    history_router,
    recs_router,
    settings_router,
    download,
    favorites_router,
):
    app.include_router(_router.router, prefix="/api", dependencies=[_guard])

# Superadmin-only surface. `require_superadmin` chains `current_user`, so an
# unauthenticated caller still gets 401 and a non-superadmin gets 403.
app.include_router(
    users_router.router,
    prefix="/api",
    dependencies=[Depends(require_superadmin)],
)


@app.get("/api/health")
async def health():
    return {"ok": True}
