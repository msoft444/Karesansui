from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import GlobalSettings
from app.schemas import SettingResponse, SettingUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=List[SettingResponse])
def list_settings(db: Session = Depends(get_db)):
    """Return all global settings ordered by key."""
    return db.query(GlobalSettings).order_by(GlobalSettings.key).all()


@router.get("/{key}", response_model=SettingResponse)
def get_setting(key: str, db: Session = Depends(get_db)):
    """Return a single setting by key."""
    record = db.get(GlobalSettings, key)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Setting not found"
        )
    return record


@router.post("/{key}", response_model=SettingResponse, status_code=status.HTTP_201_CREATED)
def create_setting(key: str, payload: SettingUpdate, db: Session = Depends(get_db)):
    """Create a new global setting. Returns 409 if the key already exists."""
    if db.get(GlobalSettings, key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Setting '{key}' already exists; use PUT to update",
        )
    record = GlobalSettings(key=key, value=payload.value)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.put("/{key}", response_model=SettingResponse)
def upsert_setting(key: str, payload: SettingUpdate, db: Session = Depends(get_db)):
    """Create or replace a global setting value (upsert by key)."""
    record = db.get(GlobalSettings, key)
    if record:
        record.value = payload.value
    else:
        record = GlobalSettings(key=key, value=payload.value)
        db.add(record)
    db.commit()
    db.refresh(record)
    return record
