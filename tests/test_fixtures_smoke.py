"""Smoke test for benchmark fixture generator and committed fixture media."""

import json
import wave
from pathlib import Path

import pytest

from lectural.acquisition import captions_are_usable, parse_vtt
from lectural.ocr import dedupe_incremental_texts
from lectural.visual import (
    PHASH_HAMMING_THRESHOLD,
    _image_phash,
    phash_hamming_distance,
    select_phash_keyframe_indices,
)

BENCHMARK_DIR = Path(__file__).parent / "fixtures" / "benchmark"
FIXTURE_IDS = ["en_terms_01", "ko_terms_01", "mixed_terms_01"]


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_fixture_directory_and_required_files(fixture_id: str):
    f_dir = BENCHMARK_DIR / fixture_id
    assert f_dir.exists(), f"Fixture dir missing: {f_dir}"
    
    # Required core files
    assert (f_dir / "gt.json").exists()
    assert (f_dir / "ground_truth.json").exists()
    assert (f_dir / "script.txt").exists()
    assert (f_dir / "audio.wav").exists()
    assert (f_dir / "audio_degraded.wav").exists()
    assert (f_dir / "video.mp4").exists()
    assert (f_dir / "video_360p.mp4").exists()
    assert (f_dir / "captions_usable.vtt").exists()
    assert (f_dir / "captions_unusable.vtt").exists()
    assert (f_dir / "captions.vtt").exists()
    
    # Slides
    slides_dir = f_dir / "slides"
    assert slides_dir.exists()
    expected_slides = [
        "slide_00_title.png",
        "slide_01_concept.png",
        "slide_02_near_dup.png",
        "slide_03_inc_base.png",
        "slide_04_inc_ext.png",
        "slide_degraded_l1.png",
        "slide_degraded_l2.png",
    ]
    for s_name in expected_slides:
        s_path = slides_dir / s_name
        assert s_path.exists(), f"Slide missing: {s_path}"
        assert s_path.stat().st_size > 1000, f"Slide empty or too small: {s_path}"


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_gt_json_schema(fixture_id: str):
    gt_path = BENCHMARK_DIR / fixture_id / "gt.json"
    with open(gt_path, encoding="utf-8") as f:
        data = json.load(f)
    
    assert data["fixture_id"] == fixture_id
    assert data["language"] in {"en", "ko", "mixed"}
    assert isinstance(data["script"], str) and len(data["script"]) > 20
    
    assert isinstance(data["speech_spans"], list)
    assert len(data["speech_spans"]) == 3
    for span in data["speech_spans"]:
        assert len(span) == 2
        assert span[0] < span[1]
    
    assert isinstance(data["slide_change_timestamps"], list)
    assert len(data["slide_change_timestamps"]) == 4
    assert data["slide_change_timestamps"] == [0.0, 5.0, 13.0, 18.0]
    
    assert isinstance(data["key_fields"], dict)
    assert len(data["key_fields"]) >= 5
    for k, v in data["key_fields"].items():
        assert isinstance(k, str) and isinstance(v, str) and len(v) > 0
    
    assert isinstance(data["usable_ocr_threshold_chars"], int)
    assert data["usable_ocr_threshold_chars"] > 0
    
    assert isinstance(data["degradation"], dict)
    assert "visual" in data["degradation"] and "audio" in data["degradation"]
    
    assert data["caption_variant"] == "usable"
    
    assert isinstance(data["independent_review"], dict)
    assert "reviewer" in data["independent_review"]
    assert "date" in data["independent_review"]
    assert "notes" in data["independent_review"]
    assert len(data["independent_review"]["notes"]) > 50


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_captions_heuristics_usable_and_unusable(fixture_id: str):
    f_dir = BENCHMARK_DIR / fixture_id
    
    # Usable captions
    usable_text = (f_dir / "captions_usable.vtt").read_text(encoding="utf-8")
    usable_segs = parse_vtt(usable_text)
    assert len(usable_segs) == 3
    assert captions_are_usable(usable_segs) is True
    
    # Unusable captions
    unusable_text = (f_dir / "captions_unusable.vtt").read_text(encoding="utf-8")
    unusable_segs = parse_vtt(unusable_text)
    assert captions_are_usable(unusable_segs) is False


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_slide_visual_dedup_and_incremental(fixture_id: str):
    slides_dir = BENCHMARK_DIR / fixture_id / "slides"
    
    # Near-duplicate test: slide_01 vs slide_02_near_dup
    h1 = _image_phash(str(slides_dir / "slide_01_concept.png"))
    h2 = _image_phash(str(slides_dir / "slide_02_near_dup.png"))
    dist = phash_hamming_distance(h1, h2)
    assert dist <= PHASH_HAMMING_THRESHOLD, f"Near-dup distance {dist} > threshold {PHASH_HAMMING_THRESHOLD}"
    
    # Distinct slide: slide_00 vs slide_01
    h0 = _image_phash(str(slides_dir / "slide_00_title.png"))
    dist_distinct = phash_hamming_distance(h0, h1)
    assert dist_distinct > PHASH_HAMMING_THRESHOLD, f"Distinct slides have distance {dist_distinct} <= {PHASH_HAMMING_THRESHOLD}"
    
    # Selection logic with persistence
    kept = select_phash_keyframe_indices([h0, h1, h2, h2])
    assert 0 in kept
    assert 1 not in kept or 2 not in kept  # one of the duplicates dropped
    
    # Incremental text build: slide 3 vs slide 4
    # In generate.py, slide 4 strictly extends slide 3
    # dedupe_incremental_texts on dummy text simulation
    texts = ["Batch Iterations: 128", "Batch Iterations: 128\nLearning Rate: 0.05\nArchitecture: Multi-layer"]
    kept_texts = dedupe_incremental_texts(texts)
    assert len(kept_texts) == 2, "Incremental slide should be kept distinct"


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_audio_format_and_degradation(fixture_id: str):
    f_dir = BENCHMARK_DIR / fixture_id
    
    # Clean audio
    with wave.open(str(f_dir / "audio.wav"), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        dur = w.getnframes() / w.getframerate()
        assert 15.0 <= dur <= 30.0
    
    # Degraded audio
    with wave.open(str(f_dir / "audio_degraded.wav"), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        dur_deg = w.getnframes() / w.getframerate()
        assert abs(dur_deg - dur) < 0.2


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_unusable_companion_directory(fixture_id: str):
    unusable_dir = BENCHMARK_DIR / f"{fixture_id}_unusable"
    assert unusable_dir.exists()
    gt_path = unusable_dir / "gt.json"
    assert gt_path.exists()
    with open(gt_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["caption_variant"] == "unusable"
    assert data["fixture_id"] == f"{fixture_id}_unusable"
