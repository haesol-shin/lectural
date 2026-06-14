"""Unit tests for OCR slide classification + re-split (AC-6). Pure, offline."""

import os
from pathlib import Path
import sys
import types

import pytest

from lectural import ocr
from lectural.ocr import (
    _ocr_paddle,
    _paddleocr_2x_lang,
    classify_slide_transition,
    dedupe_incremental_texts,
    is_slide,
    ocr_binarize_luma,
    ocr_image,
    ocr_otsu_threshold,
    ocr_roi_box,
    ocr_upscaled_size,
)


def test_is_slide_threshold():
    assert is_slide("Chapter 1: Introduction to Systems") is True
    assert is_slide("  ") is False
    assert is_slide("ok") is False  # too short


def test_duplicate_collapses():
    assert classify_slide_transition("A B C line", "A B C line") == "duplicate"


def test_incremental_buildup_kept():
    prev = "Title\nPoint one"
    cur = "Title\nPoint one\nPoint two added here"
    assert classify_slide_transition(prev, cur) == "incremental"


def test_unrelated_is_new():
    prev = "Topic A overview and details"
    cur = "Completely different topic B content"
    assert classify_slide_transition(prev, cur) == "new"


def test_incremental_below_growth_is_duplicate():
    prev = "Some long stable slide body text that barely changes"
    cur = prev + " ."  # negligible growth
    assert classify_slide_transition(prev, cur) == "duplicate"


def test_incremental_slide_resplit_keeps_each_step():
    # A slide built up line by line must NOT collapse to one frame.
    texts = [
        "Agenda",
        "Agenda\nItem 1 introduction",
        "Agenda\nItem 1 introduction\nItem 2 main concept",
        "Agenda\nItem 1 introduction\nItem 2 main concept",  # duplicate of prev
        "New section header entirely different",
    ]
    kept = dedupe_incremental_texts(texts)
    # indices 0,1,2 (build-up) + 4 (new); index 3 (dup) dropped.
    assert kept == [0, 1, 2, 4]


def test_roi_crop_geometry_keeps_center_slide_region():
    assert ocr_roi_box(1000, 500) == (35, 18, 965, 482)
    assert ocr_roi_box(1000, 500, margin_ratio=0.20, min_keep_ratio=0.80) == (100, 50, 900, 450)

    with pytest.raises(ValueError, match="positive"):
        ocr_roi_box(0, 500)


def test_upscale_geometry_preserves_aspect_and_caps_size():
    assert ocr_upscaled_size(800, 450) == (1600, 900)
    assert ocr_upscaled_size(2400, 1350) == (3200, 1800)

    with pytest.raises(ValueError, match="positive"):
        ocr_upscaled_size(100, 0)


def test_otsu_threshold_and_binarization_are_pure():
    histogram = [0] * 256
    histogram[20] = 10
    histogram[220] = 10

    threshold = ocr_otsu_threshold(histogram)

    assert 20 <= threshold < 220
    assert ocr_binarize_luma(20, threshold) == 0
    assert ocr_binarize_luma(220, threshold) == 255

    with pytest.raises(ValueError, match="256-bin"):
        ocr_otsu_threshold([1, 2, 3])


def test_preprocess_image_crops_upscales_binarizes_and_writes_temp(monkeypatch):
    calls = {}

    class FakeImage:
        def __init__(self, width: int, height: int):
            self.width = width
            self.height = height

        def __enter__(self):
            calls["entered"] = True
            return self

        def __exit__(self, *_exc_info):
            calls["exited"] = True

        def convert(self, mode: str):
            calls.setdefault("convert_modes", []).append(mode)
            return self

        def crop(self, box):
            calls["crop_box"] = box
            return FakeImage(box[2] - box[0], box[3] - box[1])

        def resize(self, size, resample):
            calls["resize"] = (size, resample)
            return FakeImage(size[0], size[1])

        def histogram(self):
            histogram = [0] * 256
            histogram[20] = 10
            histogram[220] = 10
            return histogram

        def point(self, fn, mode: str):
            calls["point"] = (fn(20), fn(220), mode)
            return self

        def save(self, path: str):
            calls["save_path"] = path
            Path(path).write_text("preprocessed")

    image_module = types.ModuleType("PIL.Image")
    image_module.Resampling = types.SimpleNamespace(BICUBIC=123)
    image_module.open = lambda path: (calls.__setitem__("open_path", path), FakeImage(1000, 500))[1]
    image_ops_module = types.ModuleType("PIL.ImageOps")
    image_ops_module.exif_transpose = lambda image: image
    pil_module = types.ModuleType("PIL")
    pil_module.Image = image_module
    pil_module.ImageOps = image_ops_module

    monkeypatch.setitem(sys.modules, "PIL", pil_module)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageOps", image_ops_module)

    derived_path = ocr._preprocess_image_for_ocr("frame.png")
    try:
        assert Path(derived_path).read_text() == "preprocessed"
        assert calls["open_path"] == "frame.png"
        assert calls["crop_box"] == (35, 18, 965, 482)
        assert calls["resize"] == ((1860, 928), 123)
        assert calls["convert_modes"] == ["RGB", "L"]
        assert calls["point"] == (0, 255, "L")
        assert calls["entered"] is True
        assert calls["exited"] is True
    finally:
        os.remove(derived_path)


def test_ocr_image_feeds_preprocessed_temp_path_and_cleans_up(monkeypatch, tmp_path):
    original = tmp_path / "frame.png"
    derived = tmp_path / "derived.png"
    original.write_text("original")
    derived.write_text("derived")
    seen = {}

    def fake_preprocess(path: str) -> str:
        seen["preprocess_input"] = path
        return str(derived)

    def fake_paddle(path: str, lang: str) -> str:
        seen["engine_path"] = path
        seen["lang"] = lang
        assert os.path.exists(path)
        return "preprocessed text"

    monkeypatch.setattr(ocr, "_preprocess_image_for_ocr", fake_preprocess)
    monkeypatch.setattr(ocr, "_ocr_paddle", fake_paddle)

    text, engine = ocr_image(str(original), prefer="paddle", lang="korean")

    assert (text, engine) == ("preprocessed text", "paddleocr")
    assert seen == {
        "preprocess_input": str(original),
        "engine_path": str(derived),
        "lang": "korean",
    }
    assert original.exists()
    assert not derived.exists()


def test_ocr_image_warns_and_uses_original_when_preprocess_fails(monkeypatch, tmp_path):
    original = tmp_path / "frame.png"
    original.write_text("original")
    seen = {}

    def fake_preprocess(path: str) -> str:
        raise RuntimeError(f"cannot preprocess {path}")

    def fake_tesseract(path: str) -> str:
        seen["engine_path"] = path
        return "fallback text"

    monkeypatch.setattr(ocr, "_preprocess_image_for_ocr", fake_preprocess)
    monkeypatch.setattr(ocr, "_ocr_tesseract", fake_tesseract)

    with pytest.warns(RuntimeWarning, match="OCR preprocessing failed"):
        text, engine = ocr_image(str(original), prefer="tesseract")

    assert (text, engine) == ("fallback text", "tesseract")
    assert seen["engine_path"] == str(original)
    assert original.exists()


def test_paddleocr_2x_fake_module_uses_compatible_language(monkeypatch):
    calls = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            calls["kwargs"] = kwargs

        def ocr(self, image_path, cls):
            calls["ocr"] = (image_path, cls)
            return [[[None, ("안녕 Hello", 0.99)]]]

    fake_module = types.ModuleType("paddleocr")
    fake_module.__version__ = "2.7.3"
    fake_module.PaddleOCR = FakePaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)

    assert _ocr_paddle("derived.png", "ko/en") == "안녕 Hello"
    assert calls["kwargs"] == {"use_angle_cls": True, "lang": "korean", "show_log": False}
    assert calls["ocr"] == ("derived.png", True)
    assert _paddleocr_2x_lang("en") == "en"


def test_paddleocr_3x_is_rejected_before_api_use(monkeypatch):
    fake_module = types.ModuleType("paddleocr")
    fake_module.__version__ = "3.0.0"
    fake_module.PaddleOCR = lambda **_kwargs: None
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)

    with pytest.raises(RuntimeError, match="PaddleOCR 3.0.0 detected"):
        _ocr_paddle("derived.png", "korean")
