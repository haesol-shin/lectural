"""OCR slide frames and handle incrementally-built slides.

PaddleOCR (PP-OCRv5, ko/en) is the primary engine; Tesseract is a degraded
fallback (with an explicit warning). The engine actually used is recorded so
coverage.json can surface degraded runs. Both engines are imported lazily.

The transition classifier (duplicate vs incremental vs new) is pure: a slide
that grows line-by-line must NOT collapse into a single deduped frame.
"""

from __future__ import annotations

import re
import warnings

from .config import INCREMENTAL_SLIDE_MIN_GROWTH, SLIDE_MIN_TEXT_CHARS
from .visual import Frame


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def is_slide(text: str, min_chars: int = SLIDE_MIN_TEXT_CHARS) -> bool:
    """Pure: a frame counts as a slide when it carries enough OCR text."""
    return len(_norm(text).replace(" ", "")) >= min_chars


def classify_slide_transition(
    prev_text: str,
    cur_text: str,
    min_growth: float = INCREMENTAL_SLIDE_MIN_GROWTH,
) -> str:
    """Pure: classify cur relative to prev as duplicate|incremental|new.

    - duplicate: same text (the dedup should drop it).
    - incremental: cur is a superset of prev (prev's lines all present) and
      adds at least `min_growth` fraction of new characters -> a new slide
      build-up step that must be KEPT.
    - new: unrelated content.
    """
    p = _norm(prev_text)
    c = _norm(cur_text)
    if not c:
        return "duplicate" if not p else "new"
    if not p:
        return "new"
    if c == p:
        return "duplicate"

    prev_lines = [ln for ln in _split_lines(prev_text) if ln]
    cur_lines = [ln for ln in _split_lines(cur_text) if ln]
    cur_set = set(cur_lines)
    is_superset = bool(prev_lines) and all(ln in cur_set for ln in prev_lines)

    if is_superset or c.startswith(p):
        growth = (len(c) - len(p)) / max(len(c), 1)
        return "incremental" if growth >= min_growth else "duplicate"
    return "new"


def _split_lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", ln).strip() for ln in (text or "").splitlines()]


def dedupe_incremental_texts(texts: list[str], min_growth: float = INCREMENTAL_SLIDE_MIN_GROWTH) -> list[int]:
    """Pure: indices to KEEP, treating incremental build-ups as distinct.

    Duplicates collapse onto the prior kept slide; incremental and new keep.
    """
    kept: list[int] = []
    prev = ""
    for i, t in enumerate(texts):
        kind = classify_slide_transition(prev, t, min_growth)
        if i == 0 or kind in ("incremental", "new"):
            kept.append(i)
            prev = t
        # duplicate -> skip, keep prev as-is
    return kept


# --- Engine-backed OCR (lazy) ----------------------------------------------

def ocr_image(image_path: str, prefer: str = "paddle", lang: str = "korean") -> tuple[str, str]:
    """Return (text, engine_used). Tries PaddleOCR, falls back to Tesseract."""
    if prefer == "paddle":
        try:
            return _ocr_paddle(image_path, lang), "paddleocr"
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"PaddleOCR unavailable ({exc}); falling back to Tesseract (degraded OCR quality).",
                RuntimeWarning,
                stacklevel=2,
            )
    return _ocr_tesseract(image_path), "tesseract"


def _ocr_paddle(image_path: str, lang: str) -> str:
    from paddleocr import PaddleOCR  # lazy

    engine = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)
    result = engine.ocr(image_path, cls=True)
    lines: list[str] = []
    for block in result or []:
        for line in block or []:
            if line and len(line) >= 2 and line[1]:
                lines.append(str(line[1][0]))
    return "\n".join(lines)


def _ocr_tesseract(image_path: str) -> str:
    import pytesseract  # lazy
    from PIL import Image  # lazy

    return pytesseract.image_to_string(Image.open(image_path), lang="kor+eng")


def ocr_frames(frames: list[Frame], prefer: str = "paddle") -> tuple[list[Frame], str]:
    """OCR each frame, classify, and keep distinct (incl. incremental) slides.

    Returns (kept_slide_frames, ocr_engine_used).
    """
    engine_used = "none"
    texts: list[str] = []
    for f in frames:
        text, engine = ocr_image(f.image_path, prefer=prefer)
        f.ocr_text = _norm(text)
        f.is_slide = is_slide(f.ocr_text)
        texts.append(f.ocr_text if f.is_slide else "")
        if engine != "none":
            engine_used = engine

    slide_frames = [f for f in frames if f.is_slide]
    slide_texts = [f.ocr_text for f in slide_frames]
    keep_idx = set(dedupe_incremental_texts(slide_texts))
    kept = [f for i, f in enumerate(slide_frames) if i in keep_idx]
    return kept, engine_used
