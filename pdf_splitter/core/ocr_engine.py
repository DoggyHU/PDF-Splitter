"""OCR engine and keyword-based value extraction.

Strategy (layered):
1. Text extraction from PDF (fast, accurate for most CAD-exported PDFs)
2. EasyOCR fallback (for scanned/image-based pages)
"""

import re
import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

# Lazy-loaded EasyOCR reader (only used as fallback)
_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        try:
            import easyocr
            _reader = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)
        except ImportError:
            logger.warning("EasyOCR not installed, OCR fallback unavailable")
            _reader = False  # sentinel: tried but failed
            return None
    if _reader is False:
        return None
    return _reader


def normalize_text(text: str) -> str:
    """Remove all whitespace for keyword matching."""
    return re.sub(r"\s+", "", text)


def _calculate_bbox_center(bbox_tuple) -> tuple[float, float]:
    """Return center (x, y) of a bbox."""
    x0, y0, x1, y1 = bbox_tuple
    return (x0 + x1) / 2, (y0 + y1) / 2


# ---- PDF text extraction layer -------------------------------------------

def extract_title_block_spans(
    pdf_path: str,
    page_index: int,
) -> list[dict]:
    """Extract all text spans from the title block area of a page.

    Returns list of dicts with keys: text, x0, y0, x1, y1, font, size.
    """
    import fitz
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    w, h = page.rect.width, page.rect.height

    # Title block: bottom strip (full width).
    # Using full width ensures portrait and landscape pages are both covered.
    roi_x0 = 0
    roi_y0 = h * 0.60
    roi_x1 = w
    roi_y1 = h

    blocks = page.get_text("dict")["blocks"]
    spans = []

    for block in blocks:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                bbox = span["bbox"]
                x0, y0, x1, y1 = bbox
                # Check if span overlaps with title block area
                if x1 >= roi_x0 and y1 >= roi_y0 and x0 <= roi_x1 and y0 <= roi_y1:
                    text = span["text"].strip()
                    if text:
                        spans.append({
                            "text": text,
                            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                            "font": span["font"],
                            "size": span["size"],
                        })

    doc.close()
    return spans


def _merge_title_block_spans(spans: list[dict]) -> list[dict]:
    """Merge adjacent single characters into words.

    Two passes:
    1. Vertical stack: chars in same x column, close in y → word
       e.g. "对""比" stacked → "对比"
    2. Horizontal spread: chars in same y row, close in x → word
       e.g. "图""纸""名""称" spread horizontally → "名称纸图"
       (CAD may use right-to-left order; reversed matching handles that)
    """
    if len(spans) < 2:
        return spans

    used = [False] * len(spans)

    # Pass 1: vertical merge (same x, spread in y)
    from_v = []
    spans_sorted_v = sorted(enumerate(spans), key=lambda s: (s[1]["x0"], s[1]["y0"]))
    for idx_i, span_i in spans_sorted_v:
        if used[idx_i]:
            continue
        if len(span_i["text"]) >= 2:
            from_v.append(span_i)
            continue

        chars = [span_i]
        x0, y0, x1, y1 = span_i["x0"], span_i["y0"], span_i["x1"], span_i["y1"]
        font, size = span_i["font"], span_i["size"]

        for idx_j, span_j in spans_sorted_v:
            if used[idx_j] or idx_j == idx_i:
                continue
            if len(span_j["text"]) >= 2:
                continue
            x_overlap = min(x1, span_j["x1"]) - max(x0, span_j["x0"])
            dy = span_j["y0"] - y1
            if x_overlap > 0 and 0 <= dy < size * 1.0 and span_j["font"] == font:
                chars.append(span_j)
                used[idx_j] = True
                x0 = min(x0, span_j["x0"])
                y0 = min(y0, span_j["y0"])
                x1 = max(x1, span_j["x1"])
                y1 = max(y1, span_j["y1"])

        if len(chars) >= 2:
            chars.sort(key=lambda s: s["y0"])
            merged_text = "".join(s["text"] for s in chars)
            from_v.append({"text": merged_text, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "font": font, "size": size})
        else:
            from_v.append(span_i)
        used[idx_i] = True

    # Pass 2: horizontal merge (same y, spread in x) of remaining single chars
    remaining = [(i, s) for i, s in enumerate(from_v) if len(s["text"]) < 2]
    if len(remaining) < 2:
        return from_v

    h_used = set()
    from_h = [s for i, s in enumerate(from_v) if i not in {r[0] for r in remaining}]
    h_sorted = sorted(remaining, key=lambda r: (r[1]["y0"], r[1]["x0"]))

    for idx_r, (orig_idx, span_i) in enumerate(h_sorted):
        if orig_idx in h_used:
            continue
        chars = [span_i]
        x0, y0, x1, y1 = span_i["x0"], span_i["y0"], span_i["x1"], span_i["y1"]
        font, size = span_i["font"], span_i["size"]

        for idx_r2, (orig_idx2, span_j) in enumerate(h_sorted):
            if orig_idx2 in h_used or orig_idx2 == orig_idx:
                continue
            y_overlap = min(y1, span_j["y1"]) - max(y0, span_j["y0"])
            dx = span_j["x0"] - x1
            if y_overlap > 0 and 0 <= dx < size * 1.0 and span_j["font"] == font:
                chars.append(span_j)
                h_used.add(orig_idx2)
                x0 = min(x0, span_j["x0"])
                y0 = min(y0, span_j["y0"])
                x1 = max(x1, span_j["x1"])
                y1 = max(y1, span_j["y1"])

        if len(chars) >= 2:
            chars.sort(key=lambda s: s["x0"])
            merged_text = "".join(s["text"] for s in chars)
            from_h.append({"text": merged_text, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "font": font, "size": size})
        else:
            from_h.append(span_i)
        h_used.add(orig_idx)

    return from_h


def _contains_ascii(text: str) -> bool:
    """Check if text contains at least one ASCII letter/digit."""
    return any(c.isascii() and (c.isalnum() or c == "-") for c in text)


def _search_below(kw_item: dict, items: list[dict], kw_norm: str, kw_cx: float) -> str | None:
    """Search for a value below the keyword with relaxed x tolerance.

    When multiple candidates are in the same x column, prefers the
    bottom-most one (closest to page bottom, where the real drawing
    number typically sits).
    """
    kw_bottom = kw_item["y1"]
    kw_width = kw_item["x1"] - kw_item["x0"]
    x_min = kw_item["x0"] - kw_width
    x_max = kw_item["x1"] + kw_width * 15

    best_value = None
    best_score = float("inf")

    for item in items:
        item_norm = normalize_text(item["text"])
        if item is kw_item or item_norm == kw_norm or kw_norm in item_norm:
            continue
        v_cx = (item["x0"] + item["x1"]) / 2
        v_top = item["y0"]

        if v_top <= kw_bottom:
            continue
        if item["x0"] < x_min or item["x0"] > x_max:
            continue

        v_dist = v_top - kw_bottom
        h_dist = abs(v_cx - kw_cx)
        # Prefer closer horizontally, then lower vertically (bottom-most)
        score = h_dist * 3 + v_dist - len(item_norm) * 5
        if score < best_score:
            best_score = score
            best_value = item["text"]

    return best_value


def find_value_by_keyword_pdf(
    pdf_path: str,
    page_index: int,
    keyword: str,
) -> str | None:
    """Use PDF text extraction to find a keyword and return the adjacent value.

    Strategy:
    1. Extract all text spans in the title block area
    2. Merge adjacent spans into logical text blocks
    3. Search for the keyword
    4. Look RIGHT (same row) or BELOW (same column) for the value
    """
    spans = extract_title_block_spans(pdf_path, page_index)
    if not spans:
        return None

    items = _merge_title_block_spans(spans)

    kw_norm = normalize_text(keyword)
    if not kw_norm:
        return None

    # Search for keyword among merged items.
    # Also check reversed text — some CAD title blocks render labels
    # with right-to-left character order (e.g. "图""纸""名""称" → "名称纸图").
    kw_item = None
    for item in items:
        item_norm = normalize_text(item["text"])
        item_rev = item_norm[::-1]
        if item_norm == kw_norm or item_rev == kw_norm:
            kw_item = item
            break
    if kw_item is None:
        for item in items:
            item_norm = normalize_text(item["text"])
            item_rev = item_norm[::-1]
            if (kw_norm in item_norm or kw_norm in item_rev) and len(item_norm) <= len(kw_norm) + 4:
                kw_item = item
                break

    if kw_item is None:
        logger.info("Keyword '%s' not found by PDF text extraction", keyword)
        return None

    logger.info("Found keyword '%s' at (%.0f, %.0f)", kw_item["text"], kw_item["x0"], kw_item["y0"])

    # Find value to the RIGHT of keyword (same row, or slightly below/above)
    kw_cx = (kw_item["x0"] + kw_item["x1"]) / 2
    kw_right_edge = kw_item["x1"]
    kw_yc = (kw_item["y0"] + kw_item["y1"]) / 2
    # Use half the font size for row tolerance, not the full merged bbox height
    # (merged vertical text spans many rows, so bbox height is misleading)
    row_tolerance = kw_item.get("size", 10) * 3

    best_value = None
    best_dist = float("inf")

    for item in items:
        item_norm = normalize_text(item["text"])
        if item is kw_item or item_norm == kw_norm or kw_norm in item_norm:
            continue

        v_cx = (item["x0"] + item["x1"]) / 2
        v_cy = (item["y0"] + item["y1"]) / 2

        # Value must be to the RIGHT of the keyword
        if v_cx <= kw_right_edge - 2:
            continue

        # Check y overlap: the value should have some y overlap with the keyword area
        kw_top = kw_item["y0"]
        kw_bot = kw_item["y1"]
        v_top = item["y0"]
        v_bot = item["y1"]
        y_overlap = min(kw_bot, v_bot) - max(kw_top, v_top)

        # Require positive y overlap — value must be at same row as keyword
        if y_overlap <= 0:
            continue

        horizontal_dist = v_cx - kw_right_edge
        # Skip items unreasonably far from keyword
        kw_width = kw_item["x1"] - kw_item["x0"]
        if horizontal_dist > kw_width * 25:
            continue
        # Prefer closer horizontal distance, then longer text
        score = horizontal_dist - len(item_norm) * 30

        if score < best_dist:
            best_dist = score
            best_value = item["text"]

    # If the RIGHT result is pure Chinese and shorter than what's below,
    # it's likely a label (not the real value). Replace with below result.
    # Portrait title blocks put values below labels.
    if best_value is not None and not _contains_ascii(best_value):
        below_best = _search_below(kw_item, items, kw_norm, kw_cx)
        if below_best is not None and len(normalize_text(below_best)) >= len(normalize_text(best_value)):
            best_value = below_best
            best_dist = float("-inf")

    if best_value is None:
        # Try BELOW the keyword with relaxed x tolerance.
        # Some title blocks (esp. portrait pages) put the value diagonally
        # below-right of the label, so strict x overlap fails.
        # Use generous rightward tolerance: from keyword's left edge
        # to keyword's right edge + 20x font width.
        kw_bottom = kw_item["y1"]
        kw_width = kw_item["x1"] - kw_item["x0"]
        x_min = kw_item["x0"] - kw_width
        x_max = kw_item["x1"] + kw_width * 15

        for item in items:
            item_norm = normalize_text(item["text"])
            if item is kw_item or item_norm == kw_norm or kw_norm in item_norm:
                continue
            v_cx = (item["x0"] + item["x1"]) / 2
            v_top = item["y0"]

            if v_top <= kw_bottom:
                continue
            # Value must be within the relaxed horizontal range
            if item["x0"] < x_min or item["x0"] > x_max:
                continue
            # Prefer closer vertically, then closer horizontally
            v_dist = v_top - kw_bottom
            h_dist = abs(v_cx - kw_cx)
            score = v_dist * 2 + h_dist - len(item_norm) * 30
            if best_value is None or score < best_dist:
                best_dist = score
                best_value = item["text"]

    return best_value


# ---- OCR fallback layer --------------------------------------------------

def _merge_vertical_chars_ocr(ocr_results: list[tuple]) -> list[tuple]:
    """Merge vertically-stacked single characters from OCR results."""
    if len(ocr_results) < 2:
        return ocr_results

    results = [(bbox, text, conf) for bbox, text, conf in ocr_results if text.strip()]
    if len(results) < 2:
        return ocr_results

    results.sort(key=lambda r: (r[0][0][1], r[0][0][0]))
    merged = []
    used = [False] * len(results)

    for i, (bbox_i, text_i, conf_i) in enumerate(results):
        if used[i]:
            continue
        if len(text_i) >= 2:
            merged.append((bbox_i, text_i, conf_i))
            continue

        chars = [text_i]
        bboxes = [bbox_i]
        confs = [conf_i]
        current_bbox = bbox_i

        for j in range(i + 1, len(results)):
            if used[j]:
                continue
            bbox_j, text_j, conf_j = results[j]
            if len(text_j) >= 2:
                continue

            cx_i = (current_bbox[0][0] + current_bbox[2][0]) / 2
            cx_j = (bbox_j[0][0] + bbox_j[2][0]) / 2
            x_dist = abs(cx_i - cx_j)
            y_gap = bbox_j[0][1] - current_bbox[2][1]
            char_width = current_bbox[2][0] - current_bbox[0][0]
            char_height = current_bbox[2][1] - current_bbox[0][1]

            if x_dist < char_width * 1.5 and 0 <= y_gap < char_height * 2:
                chars.append(text_j)
                bboxes.append(bbox_j)
                confs.append(conf_j)
                used[j] = True
                current_bbox = bbox_j

        if len(chars) >= 2:
            merged_text = "".join(chars)
            all_x = [p[0] for b in bboxes for p in b]
            all_y = [p[1] for b in bboxes for p in b]
            min_x, max_x = min(all_x), max(all_x)
            min_y, max_y = min(all_y), max(all_y)
            merged_bbox = [[min_x, min_y], [max_x, min_y], [max_x, max_y], [min_x, max_y]]
            avg_conf = sum(confs) / len(confs)
            merged.append((merged_bbox, merged_text, avg_conf))
        else:
            merged.append((bbox_i, text_i, conf_i))

        used[i] = True

    return merged


def _fallback_name_from_position_ocr(candidates: list[tuple]) -> str | None:
    """Fallback for drawing name when keyword not found in OCR."""
    if not candidates:
        return None

    img_w = max(max(p[0] for p in bbox) for bbox, _, _ in candidates)
    img_h = max(max(p[1] for p in bbox) for bbox, _, _ in candidates)
    mid_x = img_w * 0.4

    right_side = []
    for bbox, text, conf in candidates:
        cx = sum(p[0] for p in bbox) / 4
        cy = sum(p[1] for p in bbox) / 4
        if cx >= mid_x and cy < img_h * 0.40 and len(text) >= 2:
            right_side.append((bbox, text, conf))

    if not right_side:
        return None
    right_side.sort(key=lambda x: -len(x[1]))
    return right_side[0][1].strip()


def find_value_by_keyword_ocr(
    image: Image.Image,
    keyword: str,
) -> str | None:
    """OCR fallback for scanned/image-based pages."""
    import numpy as np
    reader = _get_reader()
    if reader is None:
        return None
    raw_results = reader.readtext(np.array(image), detail=1)

    if not raw_results:
        return None

    merged = _merge_vertical_chars_ocr(raw_results)

    candidates = []
    for bbox, text, conf in merged:
        text = text.strip()
        if not text or conf < 0.2:
            continue
        candidates.append((bbox, text, conf))

    if not candidates:
        return None

    kw_norm = normalize_text(keyword)
    if not kw_norm:
        return None

    # Search for keyword
    kw_bbox = None
    for bbox, text, conf in candidates:
        if normalize_text(text) == kw_norm:
            kw_bbox = bbox
            break
    if kw_bbox is None:
        for bbox, text, conf in candidates:
            text_norm = normalize_text(text)
            if kw_norm in text_norm and len(text_norm) <= len(kw_norm) + 4:
                kw_bbox = bbox
                break

    if kw_bbox is None:
        logger.info("Keyword '%s' not found by OCR, trying position fallback", keyword)
        return _fallback_name_from_position_ocr(candidates)

    # Find value to the RIGHT
    kw_cx = sum(p[0] for p in kw_bbox) / 4
    kw_cy = sum(p[1] for p in kw_bbox) / 4
    kw_w = max(p[0] for p in kw_bbox) - min(p[0] for p in kw_bbox)
    kw_h = max(p[1] for p in kw_bbox) - min(p[1] for p in kw_bbox)

    best_value = None
    best_score = float("inf")

    for bbox, text, conf in candidates:
        text_norm = normalize_text(text)
        if text_norm == kw_norm or kw_norm in text_norm:
            continue

        v_cx = sum(p[0] for p in bbox) / 4
        v_cy = sum(p[1] for p in bbox) / 4

        if v_cx <= kw_cx + kw_w * 0.5:
            continue

        kw_top = min(p[1] for p in kw_bbox)
        kw_bot = max(p[1] for p in kw_bbox)
        v_top = min(p[1] for p in bbox)
        v_bot = max(p[1] for p in bbox)
        y_overlap = min(kw_bot, v_bot) - max(kw_top, v_top)
        if y_overlap <= 0:
            continue

        horizontal_dist = v_cx - kw_cx
        score = horizontal_dist * 2 - len(text_norm) * 50 - conf * 200

        if score < best_score:
            best_score = score
            best_value = text.strip()

    if best_value is None:
        # Try below
        for bbox, text, conf in candidates:
            text_norm = normalize_text(text)
            if text_norm == kw_norm or kw_norm in text_norm:
                continue
            v_top = min(p[1] for p in bbox)
            if v_top <= kw_bot:
                continue
            kw_left = min(p[0] for p in kw_bbox)
            kw_right = max(p[0] for p in kw_bbox)
            x_overlap = min(kw_right, max(p[0] for p in bbox)) - max(kw_left, min(p[0] for p in bbox))
            if x_overlap <= 0:
                continue
            if best_value is None or conf > best_score:
                best_score = conf
                best_value = text.strip()

    return best_value
