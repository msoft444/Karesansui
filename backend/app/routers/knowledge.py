"""
knowledge.py

Knowledge Base Manager API — Phase 3 Step 1.

Endpoints:
    POST   /knowledge/upload          — Upload a PDF and trigger the ingestion pipeline.
    GET    /knowledge/                — List all knowledge documents with section hierarchy.
    GET    /knowledge/{doc_id}        — Get full detail for a single document (tree + previews).
    DELETE /knowledge/{doc_id}        — Remove a document (DB rows, GitHub, local files).
    POST   /knowledge/search          — Semantic search over the knowledge base.
"""

import shutil
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import KnowledgeChunk, KnowledgeDocument
from app.schemas import (
    KnowledgeChunkResult,
    KnowledgeDocumentDetailResponse,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSectionSummary,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

# Stable base directory for uploaded PDFs and pipeline output.
# Mounted as a Docker named volume (knowledge_uploads) shared between the
# backend API container and the Celery worker container so the worker can
# read the uploaded file after the API writes it.
_UPLOAD_BASE_DIR = "/tmp/karesansui_knowledge"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sections_for_doc(db: Session, doc: KnowledgeDocument) -> list[KnowledgeSectionSummary]:
    """Return lightweight section summaries from KnowledgeChunk rows for *doc*."""
    if not doc.source_pdf_path:
        return []
    chunks = (
        db.query(KnowledgeChunk)
        .filter(KnowledgeChunk.source_pdf == doc.source_pdf_path)
        .order_by(KnowledgeChunk.level, KnowledgeChunk.start_page)
        .all()
    )
    return [
        KnowledgeSectionSummary(
            id=str(c.id),
            section_title=c.section_title,
            level=c.level,
            start_page=c.start_page,
            end_page=c.end_page,
        )
        for c in chunks
    ]


def _chunks_for_doc(db: Session, doc: KnowledgeDocument) -> list[KnowledgeChunkResult]:
    """Return full chunk records (including content) for *doc*, ordered by hierarchy."""
    if not doc.source_pdf_path:
        return []
    chunks = (
        db.query(KnowledgeChunk)
        .filter(KnowledgeChunk.source_pdf == doc.source_pdf_path)
        .order_by(KnowledgeChunk.level, KnowledgeChunk.start_page)
        .all()
    )
    return [
        KnowledgeChunkResult(
            id=str(c.id),
            source_pdf=c.source_pdf,
            section_title=c.section_title,
            level=c.level,
            start_page=c.start_page,
            end_page=c.end_page,
            markdown_path=c.markdown_path,
            content=c.content,
            distance=0.0,  # Not a search result — distance is not applicable.
        )
        for c in chunks
    ]


def _doc_to_list_response(db: Session, doc: KnowledgeDocument) -> KnowledgeDocumentListResponse:
    """Build a KnowledgeDocumentListResponse from an ORM document record."""
    return KnowledgeDocumentListResponse(
        id=doc.id,
        filename=doc.filename,
        status=doc.status,
        error_message=doc.error_message,
        page_count=doc.page_count,
        chunk_count=doc.chunk_count,
        github_path=doc.github_path,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        sections=_sections_for_doc(db, doc),
    )


def _doc_to_detail_response(db: Session, doc: KnowledgeDocument) -> KnowledgeDocumentDetailResponse:
    """Build a KnowledgeDocumentDetailResponse from an ORM document record."""
    return KnowledgeDocumentDetailResponse(
        id=doc.id,
        filename=doc.filename,
        status=doc.status,
        error_message=doc.error_message,
        page_count=doc.page_count,
        chunk_count=doc.chunk_count,
        github_path=doc.github_path,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        sections=_sections_for_doc(db, doc),
        chunks=_chunks_for_doc(db, doc),
    )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> KnowledgeDocument:
    """Accept a PDF upload, create a tracking record, and dispatch the background pipeline.

    Returns the KnowledgeDocument record immediately with status="uploading".
    The Celery worker updates the status as the pipeline progresses through
    splitting → converting → vectorizing → syncing → completed | failed.
    """
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted.",
        )

    # Create the tracking record first so we have an ID for the temp directory.
    doc = KnowledgeDocument(filename=filename, status="uploading")
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Persist the PDF under a stable path keyed by doc.id.
    import os

    doc_dir = os.path.join(_UPLOAD_BASE_DIR, str(doc.id))
    output_dir = os.path.join(doc_dir, "output")
    os.makedirs(doc_dir, exist_ok=True)

    pdf_path = os.path.join(doc_dir, filename)
    contents = await file.read()
    with open(pdf_path, "wb") as fh:
        fh.write(contents)

    # Store paths so the DELETE handler can clean up without re-computing them.
    doc.source_pdf_path = pdf_path
    doc.output_dir = doc_dir
    db.commit()

    # Dispatch the Celery pipeline task (import deferred to avoid circular imports).
    from app.tasks import process_knowledge_document

    process_knowledge_document.delay(
        doc_id=str(doc.id),
        pdf_path=pdf_path,
        output_dir=output_dir,
    )

    return doc


# ---------------------------------------------------------------------------
# List — enriched with section hierarchy
# ---------------------------------------------------------------------------


@router.get("", response_model=List[KnowledgeDocumentListResponse])
def list_documents(db: Session = Depends(get_db)) -> list[KnowledgeDocumentListResponse]:
    """Return all knowledge documents ordered newest-first, each enriched with its
    chapter/section hierarchy (populated from persisted KnowledgeChunk rows).
    """
    docs = (
        db.query(KnowledgeDocument)
        .order_by(KnowledgeDocument.created_at.desc())
        .all()
    )
    return [_doc_to_list_response(db, doc) for doc in docs]


# ---------------------------------------------------------------------------
# Get single document — full detail including chunk previews
# ---------------------------------------------------------------------------


@router.get("/{doc_id}", response_model=KnowledgeDocumentDetailResponse)
def get_document(
    doc_id: uuid.UUID, db: Session = Depends(get_db)
) -> KnowledgeDocumentDetailResponse:
    """Return full detail for a single knowledge-base document.

    The response includes:
    - Basic document metadata and pipeline status.
    - ``sections`` — the chapter/section tree (lightweight, without content).
    - ``chunks``   — all chunk records with individual content previews.
    """
    doc = db.get(KnowledgeDocument, doc_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return _doc_to_detail_response(db, doc)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(doc_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    """Remove a document and all associated data.

    Deletion order:
    1. Delete KnowledgeChunk rows (pgvector embeddings) whose source_pdf
       matches the document's uploaded PDF path.
    2. Best-effort: recursively delete GitHub repository files if the document
       was synced (including nested chapter/section subdirectories).
    3. Best-effort: remove local temporary files.
    4. Delete the KnowledgeDocument tracking record.
    """
    doc = db.get(KnowledgeDocument, doc_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    # 1. Remove pgvector embeddings for this document.
    if doc.source_pdf_path:
        db.query(KnowledgeChunk).filter(
            KnowledgeChunk.source_pdf == doc.source_pdf_path
        ).delete(synchronize_session=False)

    # 2. Delete GitHub repository files for this document.
    # The document was synced to GitHub (github_path is set), so its files
    # must be removed. Propagate any RuntimeError (auth failure or partial
    # deletion) as HTTP 500 so the caller knows cleanup was incomplete.
    if doc.github_path:
        try:
            from app.services import github_sync

            github_sync.delete_document_files(doc.github_path)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"GitHub cleanup failed: {exc}",
            ) from exc

    # 3. Remove local temporary files (uploaded PDF + pipeline output).
    if doc.output_dir:
        try:
            shutil.rmtree(doc.output_dir)
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Local file cleanup failed: {exc}",
            ) from exc

    db.delete(doc)
    db.commit()


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------


@router.post("/search", response_model=KnowledgeSearchResponse)
def search_knowledge(
    payload: KnowledgeSearchRequest,
    db: Session = Depends(get_db),
) -> KnowledgeSearchResponse:
    """Return the top-K knowledge chunks most semantically similar to the query."""
    from app.services import vector_store

    results = vector_store.search_chunks(db=db, query=payload.query, top_k=payload.top_k)
    return KnowledgeSearchResponse(results=results)
