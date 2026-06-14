"""OCR slide frames and handle incrementally-built slides.

PaddleOCR 2.x (korean model for ko/en slide OCR) is the primary engine;
Tesseract is a degraded fallback (with an explicit warning). The engine
actually used is recorded so coverage.json can surface degraded runs.

The transition classifier (duplicate vs incremental vs new) is pure: a slide
that grows line-by-line must NOT collapse into a single deduped frame.
"""

from __future__ import annotations

import os
import re
import tempfile
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

def ocr_roi_box(
    width: int,
    height: int,
    margin_ratio: float = 0.035,
    min_keep_ratio: float = 0.80,
) -> tuple[int, int, int, int]:
    """Pure crop geometry for the slide region of interest.

    The keyframe itself remains the primary artifact; OCR uses this central
    derived ROI to shed video player borders and thin capture edges.
    """
    if width <= 0 or height <= 0:
        raise ValueError("OCR ROI requires positive image dimensions")

    safe_margin = max(0.0, min(float(margin_ratio), (1.0 - float(min_keep_ratio)) / 2.0))
    left = round(width * safe_margin)
    top = round(height * safe_margin)
    right = width - left
    bottom = height - top

    if right <= left or bottom <= top:
        return (0, 0, width, height)
    return (left, top, right, bottom)


def ocr_upscaled_size(
    width: int,
    height: int,
    scale: float = 2.0,
    max_dimension: int = 3200,
) -> tuple[int, int]:
    """Pure target size for OCR upscaling, preserving aspect ratio."""
    if width <= 0 or height <= 0:
        raise ValueError("OCR upscale requires positive image dimensions")

    factor = max(float(scale), 1.0)
    largest = max(width, height)
    if largest * factor > max_dimension:
        factor = max(max_dimension / largest, 1.0)

    return (max(1, round(width * factor)), max(1, round(height * factor)))


def ocr_otsu_threshold(histogram: list[int] | tuple[int, ...]) -> int:
    """Pure Otsu threshold from a 256-bin grayscale histogram."""
    if len(histogram) != 256:
        raise ValueError("OCR binarization requires a 256-bin grayscale histogram")

    total = sum(histogram)
    if total <= 0:
        return 127

    weighted_total = sum(level * count for level, count in enumerate(histogram))
    background_count = 0
    background_weight = 0.0
    best_variance = -1.0
    best_threshold = 127

    for level, count in enumerate(histogram):
        background_count += count
        if background_count == 0:
            continue

        foreground_count = total - background_count
        if foreground_count == 0:
            break

        background_weight += level * count
        background_mean = background_weight / background_count
        foreground_mean = (weighted_total - background_weight) / foreground_count
        variance = background_count * foreground_count * (background_mean - foreground_mean) ** 2

        if variance > best_variance:
            best_variance = variance
            best_threshold = level

    return best_threshold


def ocr_binarize_luma(value: int, threshold: int) -> int:
    """Pure high-contrast OCR binarization for one grayscale value."""
    return 255 if int(value) > int(threshold) else 0


def _pil_bicubic_resample(image_module: object) -> int:
    resampling = getattr(image_module, "Resampling", None)
    if resampling is not None:
        return getattr(resampling, "BICUBIC")
    return getattr(image_module, "BICUBIC")


def _preprocess_image_for_ocr(image_path: str) -> str:
    """Create a temporary ROI/upscaled/binarized OCR image.

    The returned path is a derived artifact owned by the caller, which must
    delete it after engine OCR. Heavy image dependencies stay lazy.
    """
    from PIL import Image, ImageOps  # lazy

    tmp_path = ""
    try:
        with Image.open(image_path) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
            roi = image.crop(ocr_roi_box(image.width, image.height))
            target_size = ocr_upscaled_size(roi.width, roi.height)
            if target_size != (roi.width, roi.height):
                roi = roi.resize(target_size, resample=_pil_bicubic_resample(Image))

            gray = roi.convert("L")
            threshold = ocr_otsu_threshold(tuple(gray.histogram()[:256]))
            binarized = gray.point(lambda value: ocr_binarize_luma(value, threshold), mode="L")

            handle = tempfile.NamedTemporaryFile(prefix="lectural_ocr_", suffix=".png", delete=False)
            tmp_path = handle.name
            handle.close()
            binarized.save(tmp_path)
            return tmp_path
    except Exception:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise



# --- Engine-backed OCR (lazy) ----------------------------------------------

def ocr_image(image_path: str, prefer: str = "paddle", lang: str = "korean") -> tuple[str, str]:
    """Return (text, engine_used). Tries PaddleOCR, falls back to Tesseract."""
    ocr_path = image_path
    derived_path = ""

    try:
        try:
            derived_path = _preprocess_image_for_ocr(image_path)
            ocr_path = derived_path
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"OCR preprocessing failed ({exc}); using original image for OCR.",
                RuntimeWarning,
                stacklevel=2,
            )

        if prefer == "paddle":
            try:
                return _ocr_paddle(ocr_path, lang), "paddleocr"
            except Exception as exc:  # noqa: BLE001
                warnings.warn(
                    f"PaddleOCR unavailable or unsupported ({exc}); "
                    "falling back to Tesseract (degraded OCR quality).",
                    RuntimeWarning,
                    stacklevel=2,
                )
        return _ocr_tesseract(ocr_path), "tesseract"
    finally:
        if derived_path and derived_path != image_path:
            try:
                os.remove(derived_path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                warnings.warn(
                    f"Could not remove temporary OCR image {derived_path!r}: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for raw_part in str(version).replace("-", ".").replace("+", ".").split("."):
        digits = ""
        for char in raw_part:
            if not char.isdigit():
                break
            digits += char
        if digits:
            parts.append(int(digits))
        elif parts:
            break
    return tuple(parts)


def _paddleocr_version(paddleocr_module: object) -> str | None:
    version = getattr(paddleocr_module, "__version__", None)
    if version is not None:
        return str(version)

    try:
        from importlib import metadata as importlib_metadata

        return importlib_metadata.version("paddleocr")
    except Exception:
        return None


def _ensure_paddleocr_2x(paddleocr_module: object) -> None:
    version = _paddleocr_version(paddleocr_module)
    if version is None:
        warnings.warn(
            "Could not detect PaddleOCR version; using PaddleOCR 2.x API compatibility path.",
            RuntimeWarning,
            stacklevel=2,
        )
        return

    parsed = _version_tuple(version)
    if parsed and parsed[0] >= 3:
        raise RuntimeError(
            f"PaddleOCR {version} detected, but LecturAL uses the PaddleOCR 2.x OCR API. "
            'Install a compatible version with `uv pip install "paddleocr>=2.7,<3"`.'
        )


def _paddleocr_2x_lang(lang: str) -> str:
    normalized = (lang or "korean").strip().lower().replace("-", "_")
    if normalized in {"ko", "kor", "korean", "ko_kr", "kor_eng", "ko_en", "ko/en", "korean_english"}:
        return "korean"
    if normalized in {"en", "eng", "english"}:
        return "en"
    raise ValueError(
        f"Unsupported PaddleOCR 2.x language {lang!r}; use 'korean' for ko/en slide OCR or 'en'."
    )


def _ocr_paddle(image_path: str, lang: str) -> str:
    import paddleocr as paddleocr_module  # lazy

    _ensure_paddleocr_2x(paddleocr_module)
    engine = paddleocr_module.PaddleOCR(
        use_angle_cls=True,
        lang=_paddleocr_2x_lang(lang),
        show_log=False,
    )
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

    with Image.open(image_path) as image:
        return pytesseract.image_to_string(image, lang="kor+eng")


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
