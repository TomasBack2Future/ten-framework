"""Private, authenticated call executor API. Never expose as public ingress."""

import asyncio
import hmac
import os
from pathlib import Path

from aiohttp import web

from .call_session import CallSessions
from .config import ExecutorConfig


def create_app(manager, token):
    """Construct a service with injected state for offline protocol tests."""
    if len(token) < 32:
        raise ValueError(
            "executor service token must have at least 32 characters"
        )

    @web.middleware
    async def boundary(request, handler):
        if request.path != "/healthz" and not hmac.compare_digest(
            request.headers.get("Authorization", ""), "Bearer " + token
        ):
            raise web.HTTPUnauthorized()
        try:
            return await handler(request)
        except KeyError as exc:
            raise web.HTTPNotFound(text="unknown session") from exc
        except PermissionError as exc:
            raise web.HTTPServiceUnavailable(text="disabled") from exc
        except OverflowError as exc:
            raise web.HTTPTooManyRequests(text="capacity reached") from exc
        except (ValueError, TypeError) as exc:
            raise web.HTTPBadRequest(text="invalid request") from exc

    app = web.Application(middlewares=[boundary], client_max_size=128 * 1024)

    async def health(_request):
        return web.json_response({"enabled": manager.config.enabled})

    async def create(_request):
        return web.json_response(manager.create(), status=201)

    async def submit(request):
        result = manager.submit(request.match_info["sid"], await request.json())
        return web.json_response(result, status=202)

    async def status(request):
        return web.json_response(
            manager.calls[request.match_info["sid"]].snapshot()
        )

    async def close(request):
        await manager.close(request.match_info["sid"])
        return web.json_response({"status": "closed"})

    async def lifetime(_app):
        async def reaper():
            while True:
                await asyncio.sleep(30)
                await manager.reap()

        task = asyncio.create_task(reaper())
        yield
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for sid in list(manager.calls):
            await manager.close(sid)

    app.cleanup_ctx.append(lifetime)
    app.router.add_get("/healthz", health)
    app.router.add_post("/sessions", create)
    app.router.add_post("/sessions/{sid}/inputs", submit)
    app.router.add_get("/sessions/{sid}", status)
    app.router.add_delete("/sessions/{sid}", close)
    return app


def main():
    """Explicit deployment switch; SDK imports remain lazy when disabled."""
    enabled = os.environ.get("JEV_CODEX_ENABLED", "false") == "true"
    if enabled and not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required when enabled")
    Path(os.environ.get("CODEX_HOME", "/work/codex")).mkdir(
        parents=True, exist_ok=True
    )
    config = ExecutorConfig(
        enabled=enabled,
        model=os.environ.get("JEV_CODEX_MODEL", "gpt-6-luna"),
        work_dir=Path("/work/artifacts"),
    )
    web.run_app(
        create_app(
            CallSessions(config), os.environ.get("JEV_EXECUTOR_TOKEN", "")
        ),
        host="0.0.0.0",
        port=8080,
        access_log=None,
    )


if __name__ == "__main__":
    main()
