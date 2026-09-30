"""Background-job state in Redis (batch zips, saved-video downloads).

Keeping it here instead of a module-level dict means it survives a backend
restart, is shared by every uvicorn worker, and a job whose process died is
reported as interrupted instead of "downloading" forever.

Layout per store ``kind``:

  job:<kind>:<id>   HASH  field -> JSON value; EXPIRE = ``ttl``
  jobs:<kind>       SET   of ids (pruned lazily when a hash has expired)

Every field is written with its own HSET, so a heartbeat and a progress update
never overwrite each other. While a job runs, ``running()`` refreshes its
``beat`` field; an unfinished job whose beat is older than ``STALE_AFTER`` is
returned as ``status="error"``.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from anyio import from_thread

from .. import deps

UNFINISHED = ("queued", "downloading")
HEARTBEAT_EVERY = 30  # seconds
STALE_AFTER = 120  # seconds without a heartbeat -> the worker is gone
INTERRUPTED = "La descarga se interrumpió (el servidor se reinició). Vuelve a intentarlo."


class JobStore:
    def __init__(self, kind: str, ttl: int = 86_400) -> None:
        self.kind = kind
        self.ttl = ttl

    def _key(self, job_id: str) -> str:
        return f"job:{self.kind}:{job_id}"

    @property
    def _index(self) -> str:
        return f"jobs:{self.kind}"

    async def create(self, job_id: str, **fields: Any) -> None:
        r = deps.get_redis()
        key = self._key(job_id)
        await r.delete(key)
        await r.hset(key, mapping=_encode({**fields, "beat": time.time()}))
        await r.expire(key, self.ttl)
        await r.sadd(self._index, job_id)

    async def update(self, job_id: str, **fields: Any) -> None:
        r = deps.get_redis()
        key = self._key(job_id)
        if not await r.exists(key):
            return
        await r.hset(key, mapping=_encode(fields))

    def update_from_thread(self, job_id: str, **fields: Any) -> None:
        """``update`` for code running in a ``run_in_threadpool`` worker."""
        from_thread.run(functools.partial(self.update, job_id, **fields))

    async def get(self, job_id: str) -> dict | None:
        raw = await deps.get_redis().hgetall(self._key(job_id))
        if not raw:
            return None
        job = {k: json.loads(v) for k, v in raw.items()}
        if (
            job.get("status") in UNFINISHED
            and time.time() - float(job.get("beat") or 0) > STALE_AFTER
        ):
            job["status"] = "error"
            job["error"] = INTERRUPTED
            job["progress"] = None
        return job

    async def delete(self, job_id: str) -> None:
        r = deps.get_redis()
        await r.delete(self._key(job_id))
        await r.srem(self._index, job_id)

    async def all(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for job_id in await deps.get_redis().smembers(self._index):
            job = await self.get(job_id)
            if job is None:
                await deps.get_redis().srem(self._index, job_id)
            else:
                out[job_id] = job
        return out

    @contextlib.asynccontextmanager
    async def running(self, job_id: str) -> AsyncIterator[None]:
        """Keep the job's heartbeat fresh for as long as the block runs."""

        async def beat() -> None:
            while True:
                await asyncio.sleep(HEARTBEAT_EVERY)
                await self.update(job_id, beat=time.time())

        task = asyncio.create_task(beat())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def _encode(fields: dict[str, Any]) -> dict[str, str]:
    return {k: json.dumps(v) for k, v in fields.items()}
