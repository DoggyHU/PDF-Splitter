# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**审图用PDF拆分器** — Desktop GUI tool for splitting engineering drawing PDFs into single-page files with auto-naming based on title block extraction. Built with Python + CustomTkinter + PyMuPDF.

Output filename format: `{seq}_{drawing_number}_{drawing_name}.pdf`

## Commands

```bash
# Run from source (development)
uv run python pdf_splitter/main.py

# Build single-file exe (slim, no EasyOCR/OCR fallback)
uv run pyinstaller --clean build_v3.spec

# Build with full OCR fallback (requires easyocr+timer)
uv run pyinstaller --clean build_full.spec  # if created

# Add dependencies (OCR fallback only if needed)
uv add easyocr
```

## Code Architecture

```
pdf_splitter/
├── main.py               # Entry point, logging setup
├── core/
│   ├── pdf_processor.py   # PyMuPDF operations: page count, split, title block image
│   ├── ocr_engine.py      # Keyword-value extraction from title block
│   │                       # 2 layers: PDF text extraction + EasyOCR fallback
│   └── naming.py          # PageInfo dataclass, analyze_page(), build_filename()
├── gui/
│   └── app.py             # CustomTkinter GUI: file select, preview table, split
└── __init__.py
```

### Core extraction pipeline (`analyze_page`)

1. **Drawing number** — Keyword search (`find_value_by_keyword_pdf`) → ASCII fallback (`extract_drawing_number`) → OCR (only if EasyOCR available)
2. **Drawing name** — Same keyword search pipeline
3. **Cover page** — Always returns `FM` + `封面`

### Keyword-value search algorithm (`find_value_by_keyword_pdf`)

The core algorithm that finds values in CAD drawing title blocks:

1. **ROI**: Bottom 40% of the page (full width) — covers both landscape and portrait pages
2. **Span extraction**: Extract all text spans from PyMuPDF with position/font data
3. **Two-pass merging**:
   - Vertical merge: single chars in same x column → word (e.g. "图"+"号" stacked)
   - Horizontal merge: single chars spread on same y row → word (e.g. right-to-left "图纸名称")
4. **Keyword search**: Exact match → reversed match (for right-to-left layout) → partial match
5. **Value lookup** (two-stage):
   - **RIGHT search** (primary): Values on the same row to the right of the keyword. Scores by distance × longer text preference. Filters out items >25× keyword width away.
   - **Below-competitive check**: If RIGHT result is pure Chinese, checks BELOW for a longer value (handles portrait page layout where values sit below labels).
   - **BELOW fallback**: If RIGHT search finds nothing, tries below with generous horizontal tolerance.

### Drawing number extraction (`extract_drawing_number`)

For ASCII-only values (SM-04, ZP-A-01):
1. Keyword-anchored: finds "图号" keyword → picks nearest ASCII candidate to the right
2. Positional fallback: sorts all ASCII candidates by (rightmost, bottom-most)

### Key edge cases handled

| Challenge | Solution |
|-----------|----------|
| Vertical text layout (portrait pages) | Full-width ROI + below-value fallback |
| Right-to-left label order ("称名纸图") | Reverse text matching in keyword search |
| Windows illegal filename chars | `sanitize_filename_part()` replaces `<>:"/\|?*` with `-` |
| CAD font encoding garbled text | PyMuPDF text extraction works for ASCII numbers/letters; Chinese may be garbled but the algorithm finds them by position |
| Dates (2025.11) mistaken as drawing numbers | `_looks_like_drawing_number()` excludes date patterns |

### Build system

- `build_v3.spec` — Slim single-file exe (~38MB). Excludes EasyOCR/torch/numpy for small size.
- Full OCR version: Add `easyocr` dependency, exclude from `excludes` list.
- Versions are preserved: `dist/PDF拆分器.exe`, `_v2.exe`, `_v3.exe`
