"""
vector_store.py

Vectorization and pgvector storage for the RAG knowledge base pipeline.

Responsibilities:
1. Generate dense embeddings from text using a lightweight local
   Sentence-Transformers model (all-MiniLM-L6-v2, 384 dimensions).
2. INSERT embedding vectors with chunk metadata into the pgvector-backed
   KnowledgeChunk table.
3. SELECT the top-K nearest chunks using cosine similarity for RAG retrieval.
"""

import threading
from typing import Any

from sentence_transformers import SentenceTransformer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk

# ---------------------------------------------------------------------------
# Embedding model (lazy singleton)
# ---------------------------------------------------------------------------

# Lightweight general-purpose model: 384-dimensional, ~22 MB on disk.
# Must match KnowledgeChunk.embedding Vector(384) definition in models.py.
_MODEL_NAME: str = "all-MiniLM-L6-v2"
_EMBEDDING_DIM: int = 384

_model: SentenceTransformer | None = None
_model_lock = threading.Lock()


def _get_model() -> SentenceTransformer:
    """Lazily load and cache the embedding model (thread-safe singleton)."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = SentenceTransformer(_MODEL_NAME)
    return _model


def embed(text_content: str) -> list[float]:
    """
    Return a normalised 384-dimensional embedding vector for *text_content*.

    The model is loaded on first call and reused for all subsequent calls.
    L2-normalisation is applied so that cosine similarity is equivalent to
    dot-product, making the pgvector `<=>` cosine-distance operator consistent.

    Args:
        text_content: Arbitrary text to embed (e.g. Markdown section body).

    Returns:
        A Python list of 384 floats in the range [-1, 1].
    """
    model = _get_model()
    vector = model.encode(text_content, normalize_embeddings=True)
    return vector.tolist()


# ---------------------------------------------------------------------------
# INSERT
# ---------------------------------------------------------------------------


def insert_chunk(
    db: Session,
    source_pdf: str,
    section_title: str,
    level: int,
    start_page: int,
    end_page: int,
    content: str,
    markdown_path: str | None = None,
    document_id: str | None = None,
) -> KnowledgeChunk:
    """
    Embed *content* and persist a KnowledgeChunk row in the database.

    The row is flushed to the DB session but NOT committed; the caller is
    responsible for committing the transaction (or rolling back on error).

    Args:
        db:             Active SQLAlchemy session.
        source_pdf:     Absolute path to the originating PDF file.
        section_title:  Heading text extracted from the TOC.
        level:          Heading depth (1 = chapter, 2+ = section).
        start_page:     Inclusive 0-indexed first page of this chunk.
        end_page:       Exclusive 0-indexed last page of this chunk.
        content:        Text to embed (typically the Markdown section body).
        markdown_path:  Optional absolute path to the converted Markdown file.

    Returns:
        The flushed KnowledgeChunk ORM object (id is available after flush).
    """
    vector = embed(content)
    import uuid as _uuid

    chunk = KnowledgeChunk(
        source_pdf=source_pdf,
        section_title=section_title,
        level=level,
        start_page=start_page,
        end_page=end_page,
        content=content,
        embedding=vector,
        markdown_path=markdown_path,
        document_id=_uuid.UUID(document_id) if document_id else None,
    )
    db.add(chunk)
    db.flush()
    return chunk


# ---------------------------------------------------------------------------
# SELECT (cosine similarity)
# ---------------------------------------------------------------------------


def search_chunks(
    db: Session,
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    Retrieve the top-K knowledge chunks most similar to *query* using cosine
    similarity against the pgvector embeddings stored in the database.

    The pgvector `<=>` operator returns cosine *distance* (0 = identical,
    2 = maximally dissimilar). Results are ordered from most to least similar.

    Args:
        db:     Active SQLAlchemy session.
        query:  Natural-language query string to vectorise and search.
        top_k:  Maximum number of results to return (default 5).

    Returns:
        A list of dicts, each containing:
            id, source_pdf, section_title, level, start_page, end_page,
            markdown_path, content, distance (float, lower = more similar).
    """
    query_vector = embed(query)
    # Serialise the vector as a pgvector literal string for the CAST expression.
    vector_literal = "[" + ",".join(str(v) for v in query_vector) + "]"

    rows = db.execute(
        text(
            """
            SELECT
                id,
                source_pdf,
                section_title,
                level,
                start_page,
                end_page,
                markdown_path,
                content,
                embedding <=> CAST(:qv AS vector) AS distance
            FROM knowledge_chunks
            ORDER BY distance
            LIMIT :k
            """
        ),
        {"qv": vector_literal, "k": top_k},
    ).fetchall()

    return [
        {
            "id": str(row.id),
            "source_pdf": row.source_pdf,
            "section_title": row.section_title,
            "level": row.level,
            "start_page": row.start_page,
            "end_page": row.end_page,
            "markdown_path": row.markdown_path,
            "content": row.content,
            "distance": float(row.distance),
        }
        for row in rows
    ]
