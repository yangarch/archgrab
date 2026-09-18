from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth_routes, cookies, files, health, jobs, resolve
from app.config import get_settings
from app.core.errors import ErrorCode, ArchGrabError
from app.core.security import mask_secrets
from app.jobs import reaper, store
from app.jobs.queue import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("archgrab")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.ensure_dirs()
    if not settings.secret_key:
        log.warning("ARCHGRAB_SECRET_KEY 미설정 — 로그인이 동작하지 않습니다. `make hashpw` 참고")

    await store.init_db()
    await manager.start()
    reaper_task = reaper.start()
    try:
        yield
    finally:
        await reaper.stop(reaper_task)
        await manager.stop()


app = FastAPI(title="archgrab", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None)

app.include_router(health.router, prefix="/api")
app.include_router(auth_routes.router, prefix="/api")
app.include_router(cookies.router, prefix="/api")
app.include_router(resolve.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(files.router, prefix="/api")


@app.exception_handler(ArchGrabError)
async def archgrab_error_handler(request: Request, exc: ArchGrabError) -> JSONResponse:
    if exc.code in {ErrorCode.INTERNAL, ErrorCode.ENGINE_FAILED}:
        log.warning("%s %s — %s", exc.code, request.url.path, mask_secrets(exc.detail or ""))
    return JSONResponse(status_code=exc.http_status, content={"error": exc.to_payload()})


# ---- SPA 서빙 -------------------------------------------------------------
# 셸(index.html·assets)은 인증 없이 내려간다. 로그인 화면 자체가 SPA 의 일부라
# 게이팅하면 로드가 불가능하고, 셸에는 어떤 데이터도 들어 있지 않다.
# 데이터가 오가는 /api/* 는 전부 require_auth 로 막혀 있다.

_static = get_settings().static_dir
if (_static / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False, response_model=None)
async def spa(full_path: str) -> Response:
    if full_path.startswith("api/"):
        return JSONResponse(status_code=404, content={"error": {"code": "NOT_FOUND"}})
    index = _static / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-store"})
    return PlainTextResponse(
        "프론트엔드가 빌드되지 않았습니다.\n"
        "개발: cd frontend && npm run dev (Vite 가 /api 를 :8000 으로 프록시)\n"
        "빌드: make build-frontend\n",
        status_code=503,
    )
