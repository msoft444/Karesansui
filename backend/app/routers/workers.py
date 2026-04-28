from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status

from app.worker import celery_app

router = APIRouter(prefix="/workers", tags=["workers"])

# Timeout (seconds) for Celery inspect calls.
# Keep short to avoid blocking the event loop; workers offline within this window
# are simply not reflected in the response rather than causing an error.
_INSPECT_TIMEOUT: float = 2.0


def _inspect_safe(method: str) -> Dict[str, Any]:
    """Call a Celery inspect method and return the result dict.

    Returns an empty dict when no workers are reachable or the call times out.
    """
    i = celery_app.control.inspect(timeout=_INSPECT_TIMEOUT)
    result = getattr(i, method)()
    return result or {}


@router.get("/", response_model=List[Dict[str, Any]])
def list_workers():
    """Return the list of active Celery workers with their state, active tasks, and stats.

    Returns an empty list when no workers are online.
    """
    active: Dict[str, Any] = _inspect_safe("active")
    stats: Dict[str, Any] = _inspect_safe("stats")

    # Use ping() to get a concrete last-heartbeat timestamp for each worker.
    # ping() returns {worker_name: [{"ok": "pong"}]} for reachable workers.
    ping_result: Dict[str, Any] = _inspect_safe("ping")
    # Record the UTC wall-clock time of this inspect call as the heartbeat for
    # every worker that responded to ping.  Workers that did not respond to ping
    # but were discovered via active/stats still appear as online (they may have
    # replied to the broker query but not to the direct ping), and their
    # last_heartbeat is set to None.
    now_iso: str = datetime.now(timezone.utc).isoformat()

    workers: List[Dict[str, Any]] = []
    # Build response from all worker names known via any of the three calls.
    all_names = set(active.keys()) | set(stats.keys()) | set(ping_result.keys())
    for name in sorted(all_names):
        last_heartbeat: Optional[str] = now_iso if name in ping_result else None
        workers.append(
            {
                "name": name,
                "status": "online",
                "active_tasks": active.get(name, []),
                "active_task_count": len(active.get(name, [])),
                "stats": stats.get(name, {}),
                "last_heartbeat": last_heartbeat,
            }
        )
    return workers


@router.get("/tasks/", response_model=Dict[str, Any])
def list_tasks():
    """Return currently active and reserved (queued) tasks across all workers.

    Returns empty lists when no workers are online.
    """
    active: Dict[str, Any] = _inspect_safe("active")
    reserved: Dict[str, Any] = _inspect_safe("reserved")

    all_active: List[Dict[str, Any]] = []
    for worker_name, tasks in active.items():
        for task in tasks:
            task["worker"] = worker_name
            all_active.append(task)

    all_reserved: List[Dict[str, Any]] = []
    for worker_name, tasks in reserved.items():
        for task in tasks:
            task["worker"] = worker_name
            all_reserved.append(task)

    return {"active": all_active, "reserved": all_reserved}


@router.get("/diagnostics", response_model=Dict[str, Any])
def get_diagnostics():
    """Return runtime diagnostic state for the inference backend.

    Probes INFERENCE_API_BASE_URL from inside the container so the result
    reflects container-to-host reachability, not browser-to-host reachability.
    A timeout on the probe is treated as potentially reachable (cold-start safe).
    """
    import os as _os
    import socket as _socket
    import urllib.error
    import urllib.request

    base_url: str = _os.environ.get(
        "INFERENCE_API_BASE_URL", "http://host.docker.internal:8000/v1"
    )
    api_key: str = _os.environ.get("INFERENCE_API_KEY", "not-required")
    probe_url = base_url.rstrip("/") + "/models"

    reachable = False
    error_detail: Optional[str] = None

    try:
        req = urllib.request.Request(
            probe_url,
            method="GET",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=5.0):
            pass
        reachable = True
    except urllib.error.HTTPError:
        # An HTTP error response means the backend process is accepting connections.
        reachable = True
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (_socket.timeout, TimeoutError)):
            # Slow or cold-starting backend — treat as potentially reachable.
            reachable = True
        else:
            error_detail = str(exc)
    except OSError as exc:
        error_detail = str(exc)

    return {
        "inference_backend_reachable": reachable,
        "inference_backend_url": base_url,
        "error": error_detail,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post(
    "/tasks/{task_id}/revoke",
    status_code=status.HTTP_200_OK,
    response_model=Dict[str, str],
)
def revoke_task(task_id: str):
    """Revoke (terminate) a running or queued task by its task ID.

    Sends a SIGTERM to the worker process executing the task and removes it
    from the queue if it has not started yet.
    """
    if not task_id or not task_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="task_id must not be empty",
        )
    celery_app.control.revoke(task_id, terminate=True)
    return {"task_id": task_id, "status": "revoked"}
