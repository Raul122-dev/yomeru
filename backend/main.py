from __future__ import annotations
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.config import STATIC_DIR, PORT, ensure_dirs
from api.routes import runs, config as config_router, typesetting as typesetting_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    yield


app = FastAPI(title="yomeru", version="0.1.0", lifespan=lifespan, docs_url="/api/docs")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(runs.router,          prefix="/api")
app.include_router(config_router.router,     prefix="/api")
app.include_router(typesetting_router.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}


# serve pre-built React SPA
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        return FileResponse(STATIC_DIR / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def no_build():
        return {"message": "frontend not found", "hint": "run: cd frontend && npm run build"}


if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    print(f"\n  yomeru  →  http://localhost:{port}")
    print(f"  docs    →  http://localhost:{port}/api/docs\n")
    log_cfg = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"default": {"format": "%(message)s"}},
        "handlers": {
            "stderr": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
                "formatter": "default",
            }
        },
        "loggers": {
            "uvicorn": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
        },
    }
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload="--dev" in sys.argv, log_config=log_cfg)
 