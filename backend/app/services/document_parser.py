"""
document_parser.py

PDF Splitting via TOC/Layout Analysis and MarkItDown Integration.

Pipeline:
1. Open the PDF with pdfplumber as the primary entry point.
2. Extract the Table of Contents via pdfplumber's underlying pdfminer
   document and resolve each bookmark to a 0-indexed page number.
3. Build hierarchical section descriptors:
   - Level-1 (chapter) boundary spans to the next level-1 entry.
   - Level-2+ (section) boundary spans to the next entry at same or
     higher level (numerically lower or equal level number).
   Detect tables/figures crossing page boundaries using pdfplumber
   bounding boxes and dynamically adjust split points accordingly.
4. Write each section's pages to a physical directory hierarchy:
   <output_base_dir>/chapter_N/chapter_N.pdf  (level-1 entries)
   <output_base_dir>/chapter_N/section_M.pdf  (level-2+ entries)
5. Convert each split PDF to Markdown via a subprocess calling `markitdown`.
"""

import subprocess
import sys
from pathlib import Path

import pdfplumber
import pypdf

# Points from the page edge within which an element is considered
# to be "touching" the page boundary (i.e. potentially cross-boundary).
_BOUNDARY_THRESHOLD_PT: float = 15.0


# ---------------------------------------------------------------------------
# TOC Extraction (pdfplumber-based)
# ---------------------------------------------------------------------------


def _build_page_id_map(plumber_pdf: pdfplumber.PDF) -> dict[int, int]:
    """
    Build a mapping of {pdfminer page object-id: 0-indexed page number}
    by iterating pdfplumber's authoritative page list.
    """
    page_id_map: dict[int, int] = {}
    for idx, page in enumerate(plumber_pdf.pages):
        # pdfplumber.Page wraps a pdfminer PDFPage in page.page_obj;
        # PDFPage.pageid is the PDF object ID of that page resource.
        pdf_page = page.page_obj
        pageid = getattr(pdf_page, "pageid", None)
        if pageid is not None:
            page_id_map[pageid] = idx
    return page_id_map


def _resolve_dest_to_page(
    dest,
    action,
    doc,
    page_id_map: dict[int, int],
) -> int | None:
    """
    Resolve a pdfminer bookmark destination or GoTo action to a 0-indexed
    page number using the pre-built page_id_map.

    Handles named destinations (strings) and explicit array destinations
    ([page_ref, /XYZ|/Fit|…, …]), as well as action-dict GoTo entries.
    """
    from pdfminer.pdftypes import resolve1

    # Named destination → look up the actual destination list
    if isinstance(dest, str):
        try:
            dest = resolve1(doc.get_dest(dest))
        except Exception:
            dest = None

    # Explicit destination: [page_ref, /XYZ | /Fit | ..., ...]
    if isinstance(dest, list) and dest:
        page_ref = dest[0]
        objid = getattr(page_ref, "objid", None)
        if objid is not None:
            return page_id_map.get(objid)

    # Resolve PDFObjRef before inspecting as a dict (pdfminer's
    # get_outlines() returns action as PDFObjRef, not a plain dict).
    if action is not None:
        try:
            action = resolve1(action)
        except Exception:
            action = None

    # GoTo action fallback (bytes or str keys depending on pdfminer version)
    if action and isinstance(action, dict):
        try:
            action_dest = resolve1(
                action.get(b"D") or action.get("D")
            )
            if isinstance(action_dest, list) and action_dest:
                page_ref = action_dest[0]
                objid = getattr(page_ref, "objid", None)
                if objid is not None:
                    return page_id_map.get(objid)
        except Exception:
            pass

    return None


def _extract_toc(pdf_path: str) -> list[dict]:
    """
    Extract the Table of Contents using pdfplumber as the primary entry point.

    Opens the PDF with pdfplumber, builds a pdfminer page-object-id map from
    pdfplumber's page list, then walks the PDF outline via the underlying
    pdfminer document to produce a flat, ordered list of section descriptors.

    Returns:
        [{"title": str, "level": int, "page": int (0-indexed)}, ...]
        or an empty list when no outline is embedded in the document.
    """
    entries: list[dict] = []
    try:
        with pdfplumber.open(pdf_path) as plumber_pdf:
            page_id_map = _build_page_id_map(plumber_pdf)
            doc = plumber_pdf.doc
            try:
                for level, title, dest, action, se in doc.get_outlines():
                    if not title:
                        continue
                    page_num = _resolve_dest_to_page(
                        dest, action, doc, page_id_map
                    )
                    if page_num is not None:
                        entries.append(
                            {
                                "title": str(title).strip(),
                                "level": level,
                                "page": page_num,
                            }
                        )
            except Exception:
                pass
    except Exception:
        pass
    return entries


# ---------------------------------------------------------------------------
# Cross-boundary Element Detection
# ---------------------------------------------------------------------------


def _has_cross_boundary_element(
    plumber_pdf: pdfplumber.PDF,
    page_idx: int,
) -> bool:
    """
    Return True if a table or figure visually straddles the boundary between
    page_idx and page_idx + 1, making a split at that boundary undesirable.

    Detection rules (pdfplumber top-origin coordinate system):
    - A table/image whose bottom edge is within _BOUNDARY_THRESHOLD_PT of the
      current page's bottom → likely continues on the next page.
    - A table/image whose top edge is within _BOUNDARY_THRESHOLD_PT of the
      next page's top → likely started on the previous page.
    """
    pages = plumber_pdf.pages
    if page_idx >= len(pages) - 1:
        return False

    current = pages[page_idx]
    nxt = pages[page_idx + 1]
    thr = _BOUNDARY_THRESHOLD_PT

    # --- Current page: element near the bottom ---
    try:
        for tbl in current.find_tables():
            # bbox = (x0, top, x1, bottom); bottom is distance from page top
            if current.height - tbl.bbox[3] < thr:
                return True
    except Exception:
        pass

    try:
        for img in current.images:
            if current.height - img["bottom"] < thr:
                return True
    except Exception:
        pass

    # --- Next page: element near the top ---
    try:
        for tbl in nxt.find_tables():
            if tbl.bbox[1] < thr:
                return True
    except Exception:
        pass

    try:
        for img in nxt.images:
            if img.get("top", nxt.height) < thr:
                return True
    except Exception:
        pass

    return False


# ---------------------------------------------------------------------------
# Section Building
# ---------------------------------------------------------------------------


def _build_sections(
    pdf_path: str,
    toc: list[dict],
    total_pages: int,
) -> list[dict]:
    """
    Build section descriptors from a flat TOC list, respecting heading hierarchy.

    Boundary rules:
    - Level-1 (chapter): end = start of the next level-1 entry (or total_pages).
    - Level-2+ (section): end = start of the next entry at the same or higher
      level (numerically lower or equal level number), or the next chapter.

    This ensures chapter PDFs contain all pages up to the next chapter, while
    section PDFs contain only their own content — allowing non-overlapping
    granularity at both levels.

    After computing initial boundaries, pdfplumber bounding-box analysis is
    applied to extend any boundary that would sever a cross-page visual element.

    Returns:
        [{"title": str, "level": int, "start": int, "end": int}, ...]
        where start is inclusive and end is exclusive (0-indexed pages).
    """
    if not toc:
        return [{"title": "document", "level": 1, "start": 0, "end": total_pages}]

    sections: list[dict] = []
    for i, entry in enumerate(toc):
        start = entry["page"]
        level = entry["level"]

        # Find end: next entry at the same or strictly higher level
        # (a lower level number means a higher heading rank).
        end = total_pages
        for j in range(i + 1, len(toc)):
            if toc[j]["level"] <= level:
                end = toc[j]["page"]
                break

        if start >= end:
            continue

        sections.append(
            {
                "title": entry["title"],
                "level": level,
                "start": start,
                "end": end,
            }
        )

    # Adjust split boundaries for cross-boundary visual elements.
    #
    # When a table or figure straddles the boundary between two consecutive
    # sibling sections, extend the *current* section's end by one page so the
    # visual element is captured intact.  The *next* section's start is
    # intentionally left unchanged so that hierarchy integrity is preserved:
    #
    #   • Avoiding the update means a chapter boundary cannot be shifted in a
    #     way that would make the chapter PDF start *after* its child section
    #     PDFs, which would break the physical directory hierarchy.
    #   • The one-page overlap (the boundary page appears in both the current
    #     section PDF and the next) is acceptable — it ensures the straddling
    #     element is complete in the section that logically contains it.
    #
    # Parent-child pairs are naturally excluded: a chapter and its first
    # sub-section share the same *start* page, so their ends/starts never form
    # a shared split point (sections[i]["end"] != sections[i+1]["start"]).
    with pdfplumber.open(pdf_path) as plumber_pdf:
        for i in range(len(sections) - 1):
            if sections[i]["end"] != sections[i + 1]["start"]:
                # Not a shared split point — skip parent-child and non-adjacent
                # pairs to preserve the chapter/section hierarchy.
                continue
            split_after = sections[i]["end"] - 1
            if _has_cross_boundary_element(plumber_pdf, split_after):
                # Extend only the current section; leave the next section's
                # start untouched to avoid cascading hierarchy breakage.
                sections[i]["end"] += 1

    return sections


# ---------------------------------------------------------------------------
# PDF Splitting
# ---------------------------------------------------------------------------


def _section_output_path(
    base_dir: Path,
    section: dict,
    chapter_counter: list[int],
    section_counter: list[int],
) -> Path:
    """
    Compute and create the filesystem path for a section's split PDF.

    Directory convention:
        Level-1 heading  →  <base_dir>/chapter_N/chapter_N.pdf
        Level-2+ heading →  <base_dir>/chapter_N/section_M.pdf
    """
    if section["level"] == 1:
        chapter_counter[0] += 1
        section_counter[0] = 0
        folder = base_dir / f"chapter_{chapter_counter[0]}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"chapter_{chapter_counter[0]}.pdf"
    else:
        section_counter[0] += 1
        folder = base_dir / f"chapter_{chapter_counter[0]}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"section_{section_counter[0]}.pdf"


def _write_section_pdf(
    src_path: str,
    section: dict,
    dest_path: Path,
) -> None:
    """
    Extract the page range defined by *section* from the source PDF and write
    it to *dest_path* using pypdf.
    """
    reader = pypdf.PdfReader(src_path)
    writer = pypdf.PdfWriter()

    start = section["start"]
    end = min(section["end"], len(reader.pages))
    for page_idx in range(start, end):
        writer.add_page(reader.pages[page_idx])

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with dest_path.open("wb") as fh:
        writer.write(fh)


# ---------------------------------------------------------------------------
# Markdown Conversion
# ---------------------------------------------------------------------------


def _convert_to_markdown(pdf_path: Path) -> Path:
    """
    Convert a split PDF to Markdown using the `markitdown` CLI tool.

    Writes <stem>.md alongside the PDF and returns the Markdown file path.

    Raises:
        RuntimeError: when the markitdown subprocess exits with a non-zero
                      status code.
    """
    md_path = pdf_path.with_suffix(".md")
    result = subprocess.run(
        ["markitdown", str(pdf_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"markitdown failed for {pdf_path}: {result.stderr.strip()}"
        )
    md_path.write_text(result.stdout, encoding="utf-8")
    return md_path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_and_split(
    src_pdf_path: str,
    output_base_dir: str,
) -> list[dict]:
    """
    Main entry point for the knowledge-base ingestion pipeline.

    Splits *src_pdf_path* by its embedded TOC into a physical directory
    hierarchy under *output_base_dir*, converts each section to Markdown,
    and returns metadata for every produced artifact.

    Args:
        src_pdf_path:    Absolute path to the source PDF file.
        output_base_dir: Root directory for all output files.  Created if
                         it does not yet exist.

    Returns:
        A list of dicts — one per section — with the following keys::

            {
                "pdf":      str | None,   # path to the split PDF
                "markdown": str | None,   # path to the Markdown file
                "title":    str,          # section heading from the TOC
                "level":    int,          # heading depth (1 = chapter, …)
                "start":    int,          # first page index (inclusive, 0-based)
                "end":      int,          # last page index  (exclusive, 0-based)
            }

        Markdown conversion failures are logged to stderr but do not abort
        the pipeline; ``"markdown"`` will be ``None`` for those sections.
    """
    base_dir = Path(output_base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    reader = pypdf.PdfReader(src_pdf_path)
    total_pages = len(reader.pages)

    toc = _extract_toc(src_pdf_path)
    sections = _build_sections(src_pdf_path, toc, total_pages)

    chapter_counter: list[int] = [0]
    section_counter: list[int] = [0]
    results: list[dict] = []

    for section in sections:
        if section["start"] >= section["end"]:
            continue

        dest_path = _section_output_path(
            base_dir, section, chapter_counter, section_counter
        )
        _write_section_pdf(src_pdf_path, section, dest_path)

        md_path: Path | None = None
        try:
            md_path = _convert_to_markdown(dest_path)
        except RuntimeError as exc:
            print(f"[document_parser] WARNING: {exc}", file=sys.stderr)

        results.append(
            {
                "pdf": str(dest_path),
                "markdown": str(md_path) if md_path else None,
                "title": section["title"],
                "level": section["level"],
                "start": section["start"],
                "end": section["end"],
            }
        )

    return results
