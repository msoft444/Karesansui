from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db


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


@app.get("/health")
def health_check():
    return {"status": "ok"}
