from __future__ import annotations
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from yomeru.core.config import STATIC_DIR, PORT, ensure_dirs
from yomeru.api.routes import (
    runs,
    config as config_router,
    phases as phases_router,
    editing as editing_router,
    outputs as outputs_router,
    fonts as fonts_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    yield


app = FastAPI(title="yomeru", version="0.1.0", lifespan=lifespan, docs_url="/api/docs")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(runs.router,              prefix="/api")
app.include_router(config_router.router,     prefix="/api")
app.include_router(editing_router.router,    prefix="/api")
app.include_router(outputs_router.router,    prefix="/api")
app.include_router(fonts_router.router,      prefix="/api")
app.include_router(phases_router.router,     prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui/")


# ── Serve React SPA at /ui ─────────────────────────────────────────────────────
if STATIC_DIR.exists():
    app.mount("/ui/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="ui-assets")

    @app.get("/ui/{path:path}", include_in_schema=False)
    def ui_spa(path: str):
        """Serve index.html for all /ui/* routes (React Router handles client routing)."""
        return FileResponse(STATIC_DIR / "index.html")
else:
    @app.get("/ui/{path:path}", include_in_schema=False)
    def ui_not_built(path: str = ""):
        return {"message": "UI not built", "hint": "run: cd ui && npm run build"}
