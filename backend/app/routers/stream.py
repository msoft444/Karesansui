import asyncio
import json

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.database import SessionLocal
from app.models import History

router = APIRouter(prefix="/stream", tags=["stream"])

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------
_POLL_INTERVAL: float = 1.0    # seconds between DB polls
_HEARTBEAT_EVERY: int = 15      # seconds between SSE keepalive comments


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _serialize(record: History) -> str:
    """Serialise a History record to a single SSE ``data:`` frame."""
    payload = {
        "id": str(record.id),
        "run_id": record.run_id,
        "task_id": record.task_id,
        "role": record.role,
        "result": record.result,
        "progress": record.progress,
        "created_at": record.created_at.isoformat(),
    }
    return f"data: {json.dumps(payload)}\n\n"


async def _event_stream(run_id: str):
    """Async generator that polls the DB and yields SSE frames.

    A new DB session is created *inside* the generator so it outlives the
    request handler scope (required for ``StreamingResponse``).  The session
    is always closed in the ``finally`` block regardless of how the client
    disconnects.
    """
    db = SessionLocal()
    sent_ids: set[str] = set()
    loop = asyncio.get_event_loop()
    last_heartbeat = loop.time()

    try:
        while True:
            # Fetch records for this run ordered oldest → newest so the
            # terminal displays chronological output.
            records = (
                db.query(History)
                .filter(History.run_id == run_id)
                .order_by(History.created_at.asc())
                .all()
            )
            # Expire the identity-map cache so the next poll sees fresh rows.
            db.expire_all()

            for record in records:
                rid = str(record.id)
                if rid not in sent_ids:
                    sent_ids.add(rid)
                    yield _serialize(record)

            # Heartbeat keepalive — SSE comment lines keep the connection alive
            # through proxies and load balancers that would otherwise time out.
            now = loop.time()
            if now - last_heartbeat >= _HEARTBEAT_EVERY:
                yield ": keepalive\n\n"
                last_heartbeat = now

            await asyncio.sleep(_POLL_INTERVAL)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/progress")
async def stream_progress(
    run_id: str = Query(..., description="The run_id whose History records to stream"),
):
    """Server-Sent Events endpoint for live agent progress.

    Yields ``data: {json}\\n\\n`` frames for every ``History`` record
    associated with *run_id*.  Existing records are flushed immediately on
    first connect; new records are delivered within one poll interval (~1 s).

    The stream runs indefinitely until the client disconnects and sends
    ``": keepalive"`` comments every 15 s to prevent proxy timeouts.
    """
    return StreamingResponse(
        _event_stream(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",    # disable nginx / proxy buffering
        },
    )
