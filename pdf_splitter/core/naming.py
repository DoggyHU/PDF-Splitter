"""Naming logic: extract fields from each page and build output filename."""

import re
import logging
from dataclasses import dataclass

from .pdf_processor import extract_title_block_image, extract_drawing_number
from .ocr_engine import find_value_by_keyword_pdf, find_value_by_keyword_ocr

logger = logging.getLogger(__name__)

# Windows filename illegal characters: < > : " / \ | ? *
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_filename_part(s: str) -> str:
    """Replace Windows-illegal filename characters with hyphens."""
    return _ILLEGAL_CHARS.sub("-", s)


@dataclass
class PageInfo:
    """Metadata for a single page."""
    index: int           # 0-based page index
    drawing_number: str  # e.g. "SM-04"
    drawing_name: str    # e.g. "绿化设计说明二"


def analyze_page(
    pdf_path: str,
    page_index: int,
    dn_keyword: str,
    name_keyword: str,
    is_cover: bool = False,
) -> PageInfo:
    """Analyze a single page and extract drawing number + drawing name.

    Strategy:
    1. Try PDF text extraction first (fast, accurate for CAD-exported PDFs)
    2. Fall back to EasyOCR for image-based pages
    """
    if is_cover:
        return PageInfo(index=page_index, drawing_number="FM", drawing_name="封面")

    # --- Drawing number ---
    # Try keyword-based first (works for both landscape and portrait)
    dn = find_value_by_keyword_pdf(pdf_path, page_index, dn_keyword)
    # Then ASCII pattern extraction as fallback
    if dn is None:
        dn = extract_drawing_number(pdf_path, page_index, keyword=dn_keyword)

    if dn is None:
        # OCR fallback
        try:
            img, _, _ = extract_title_block_image(pdf_path, page_index)
            dn_ocr = find_value_by_keyword_ocr(img, dn_keyword)
            if dn_ocr and len(dn_ocr) <= 20:
                dn = dn_ocr
        except Exception as e:
            logger.warning("OCR fallback for drawing number failed: %s", e)

    if dn is None:
        logger.warning("Could not find drawing number for page %d", page_index + 1)
        dn = "无图号"

    # --- Drawing name ---
    name = find_value_by_keyword_pdf(pdf_path, page_index, name_keyword)

    if name is None:
        # OCR fallback
        try:
            img, _, _ = extract_title_block_image(pdf_path, page_index)
            name = find_value_by_keyword_ocr(img, name_keyword)
        except Exception as e:
            logger.warning("OCR fallback for drawing name failed: %s", e)

    if name is None:
        logger.warning("Could not find drawing name for page %d", page_index + 1)
        name = "无图名"

    return PageInfo(index=page_index, drawing_number=dn, drawing_name=name)


def build_filename(page_num: int, info: PageInfo) -> str:
    dn = sanitize_filename_part(info.drawing_number)
    name = sanitize_filename_part(info.drawing_name)
    return f"{page_num}_{dn}_{name}.pdf"
