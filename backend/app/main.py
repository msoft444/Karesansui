import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.routers import history, settings, stream, templates
from app.routers import knowledge
from app.routers import workers
from app.routers import query


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run DB initialisation (pgvector extension + table creation) on startup."""
    init_db()
    yield


app = FastAPI(
    title="Karesansui",
    description="Ternary Bonsai Multi-Agent System API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — origins are injected via ALLOWED_ORIGINS env var (comma-separated).
# Credentials are never hardcoded; the default permits only the local frontend.
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000")
allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(history.router)
app.include_router(settings.router)
app.include_router(stream.router)
app.include_router(templates.router)
app.include_router(knowledge.router)
app.include_router(workers.router)
app.include_router(query.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
