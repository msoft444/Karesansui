import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import RoleTemplate
from app.schemas import RoleTemplateCreate, RoleTemplateResponse, RoleTemplateUpdate

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("/", response_model=List[RoleTemplateResponse])
def list_templates(db: Session = Depends(get_db)):
    """Return all role templates ordered by name."""
    return db.query(RoleTemplate).order_by(RoleTemplate.name).all()


@router.get("/{template_id}", response_model=RoleTemplateResponse)
def get_template(template_id: uuid.UUID, db: Session = Depends(get_db)):
    """Return a single role template by ID."""
    record = db.get(RoleTemplate, template_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    return record


@router.post("/", response_model=RoleTemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(payload: RoleTemplateCreate, db: Session = Depends(get_db)):
    """Create a new role template. Returns 409 if the name already exists."""
    existing = db.query(RoleTemplate).filter(RoleTemplate.name == payload.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Template '{payload.name}' already exists",
        )
    record = RoleTemplate(**payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.put("/{template_id}", response_model=RoleTemplateResponse)
def update_template(
    template_id: uuid.UUID, payload: RoleTemplateUpdate, db: Session = Depends(get_db)
):
    """Partially update an existing role template."""
    record = db.get(RoleTemplate, template_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    # Check for name uniqueness if the name is being changed
    if payload.name is not None and payload.name != record.name:
        conflict = (
            db.query(RoleTemplate).filter(RoleTemplate.name == payload.name).first()
        )
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Template '{payload.name}' already exists",
            )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(record, field, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete a role template by ID."""
    record = db.get(RoleTemplate, template_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    db.delete(record)
    db.commit()
