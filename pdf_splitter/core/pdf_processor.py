"""PDF core operations: splitting, title block extraction."""

import fitz
from pathlib import Path


def get_page_count(pdf_path: str) -> int:
    """Return the number of pages in a PDF."""
    doc = fitz.open(pdf_path)
    count = doc.page_count
    doc.close()
    return count


def split_to_pages(pdf_path: str, output_dir: str) -> list[str]:
    """Split PDF into single-page files, return list of temp file paths."""
    doc = fitz.open(pdf_path)
    temp_paths: list[str] = []
    for i in range(doc.page_count):
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=i, to_page=i)
        temp_path = str(Path(output_dir) / f"_page_{i + 1}.pdf")
        new_doc.save(temp_path)
        new_doc.close()
        temp_paths.append(temp_path)
    doc.close()
    return temp_paths


def extract_title_block_image(pdf_path: str, page_index: int) -> tuple:
    """Extract the title block region from a page as a PIL Image.

    The title block is assumed to be in the bottom-right corner:
    - right 18% of page width
    - bottom 32% of page height

    Returns (PIL.Image, page_width, page_height).
    """
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    w, h = page.rect.width, page.rect.height

    # Title block area: bottom-right corner
    roi_x0 = w * 0.82
    roi_y0 = h * 0.68
    roi_x1 = w
    roi_y1 = h

    mat = fitz.Matrix(5.0, 5.0)  # 5x zoom for small Chinese text OCR
    clip = fitz.Rect(roi_x0, roi_y0, roi_x1, roi_y1)
    pix = page.get_pixmap(matrix=mat, clip=clip)
    doc.close()

    from PIL import Image
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return img, w, h


def save_single_page_pdf(template_path: str, output_path: str, page_index: int):
    """Save a single page from the source PDF as a new PDF file."""
    doc = fitz.open(template_path)
    new_doc = fitz.open()
    new_doc.insert_pdf(doc, from_page=page_index, to_page=page_index)
    new_doc.save(output_path)
    new_doc.close()
    doc.close()


def extract_drawing_number(pdf_path: str, page_index: int, keyword: str = "图号") -> str | None:
    """Try to extract drawing number via text extraction (for ASCII values like SM-04).

    Strategy:
    1. Find the '图号' keyword in the title block bottom strip
    2. Look for the nearest ASCII value to the RIGHT of the keyword
    3. Fall back to scoring candidates by position (rightmost/bottom-most)

    Returns None if no ASCII drawing number pattern is found.
    """
    import fitz
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    w, h = page.rect.width, page.rect.height

    # Title block: bottom strip, full width
    y0 = h * 0.60

    blocks = page.get_text("blocks")
    candidates: list[tuple[str, float, float]] = []

    for b in blocks:
        bx0, by0, bx1, by1 = b[0], b[1], b[2], b[3]
        if by0 < y0 or by1 > h:
            continue
        text = b[4].strip()
        if text and _looks_like_drawing_number(text):
            candidates.append((text, bx0, by0))

    doc.close()

    if not candidates:
        return None

    # Strategy 1: find keyword anchor, pick nearest candidate to its right
    kw_norm = keyword.replace(" ", "")
    doc2 = fitz.open(pdf_path)
    page2 = doc2[page_index]
    all_blocks = page2.get_text("blocks")
    doc2.close()

    kw_right_edge = None
    kw_yc = None
    for b in all_blocks:
        bx0, by0, bx1, by1 = b[0], b[1], b[2], b[3]
        if by0 >= y0:
            text = b[4].strip().replace(" ", "")
            if kw_norm in text and len(text) <= len(kw_norm) + 4:
                kw_right_edge = bx1
                kw_yc = (by0 + by1) / 2
                break

    if kw_right_edge is not None:
        # Among candidates to the right of keyword, pick the nearest one
        best = None
        best_dist = float("inf")
        for text, bx0, by0 in candidates:
            if bx0 > kw_right_edge - 2:
                dist = (bx0 - kw_right_edge) + abs(by0 - kw_yc) * 2
                if dist < best_dist:
                    best_dist = dist
                    best = text
        if best is not None:
            return best

    # Strategy 2: prefer rightmost, then bottom-most
    candidates.sort(key=lambda c: (c[1], c[2]), reverse=True)
    return candidates[0][0]


def _looks_like_drawing_number(text: str) -> bool:
    """Check if text looks like a drawing number (e.g. SM-04, ZP-A-01, J4-01).

    Excludes pure dates (2025.11) and numbers-only strings.
    """
    import re
    if re.match(r"^\d{4}\.\d{2}$", text):  # date like 2025.11
        return False
    if re.match(r"^\d+(\.\d+)?$", text):   # pure number
        return False
    return bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9\-_\.]+$", text))
