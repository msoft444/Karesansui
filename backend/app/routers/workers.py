from typing import Any, Dict, List

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

    workers: List[Dict[str, Any]] = []
    # Build response from all worker names known via either active or stats.
    all_names = set(active.keys()) | set(stats.keys())
    for name in sorted(all_names):
        workers.append(
            {
                "name": name,
                "status": "online",
                "active_tasks": active.get(name, []),
                "active_task_count": len(active.get(name, [])),
                "stats": stats.get(name, {}),
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
