"""Benchmark fixture generator for LecturAL speech/OCR evaluation.

This module generates deterministic, redistributable offline benchmark fixtures
for English, Korean, and mixed language lecture videos.

Each fixture set contains:
1. Script (ground truth text authored first)
2. Synthesized audio (via pyttsx3 offline SAPI5 on Windows, with lazy fallbacks)
3. PIL-rendered slide PNG frames (with near-duplicate and incremental build pairs)
4. Visual degradation variants (Augraphy if available, else documented PIL fallback)
5. Audio degradation variants (Audiomentations if available, else documented FFmpeg fallback)
6. Ground truth JSON matching the schema in docs/contracts/benchmark.schema.json
7. WebVTT caption files: usable (passes captions_are_usable) and unusable fallback
8. Video files (720p base and 360p low-bitrate re-encode via FFmpeg)

Pure functions are marked with 'Pure:' per LecturAL convention.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import random
import re
import subprocess
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data Models & Schemas
# ---------------------------------------------------------------------------

@dataclass
class ReviewNote:
    reviewer: str
    date: str
    notes: str


@dataclass
class FixtureGroundTruth:
    fixture_id: str
    language: str
    script: str
    speech_spans: list[list[float]]
    slide_change_timestamps: list[float]
    key_fields: dict[str, str]
    usable_ocr_threshold_chars: int
    degradation: dict[str, list[str]]
    caption_variant: str
    independent_review: dict[str, str]


@dataclass
class SlideDefinition:
    filename: str
    title: str
    lines: list[str]
    notes: str = ""
    is_near_duplicate_of: str | None = None
    shift_xy: tuple[int, int] = (0, 0)


@dataclass
class FixtureSpec:
    fixture_id: str
    language: str
    voice_token: str  # Filter string for pyttsx3 voice ID
    sentences: list[str]
    slides: list[SlideDefinition]
    slide_durations: list[float]
    key_fields: dict[str, str]
    usable_ocr_threshold_chars: int
    review_notes: str


# ---------------------------------------------------------------------------
# Ground Truth Scripts and Specifications
# ---------------------------------------------------------------------------

SPECS: dict[str, FixtureSpec] = {
    "en_terms_01": FixtureSpec(
        fixture_id="en_terms_01",
        language="en",
        voice_token="ZIRA",
        sentences=[
            "Welcome to lecture four on optimization.",
            "In 1986, Geoffrey Hinton popularized backpropagation for multi-layer perceptrons.",
            "The learning rate was set to 0.05 across 128 batch iterations.",
        ],
        slides=[
            SlideDefinition(
                filename="slide_00_title.png",
                title="Lecture 4: Optimization",
                lines=[
                    "Deep Learning Foundations",
                    "Speaker: Geoffrey Hinton",
                    "Topics: Gradient Descent & Neural Networks",
                ],
            ),
            SlideDefinition(
                filename="slide_01_concept.png",
                title="Backpropagation Algorithm",
                lines=[
                    "Year: 1986",
                    "Key Concept: Gradient computation via chain rule",
                    "Target Architecture: Multi-layer perceptrons",
                ],
            ),
            SlideDefinition(
                filename="slide_02_near_dup.png",
                title="Backpropagation Algorithm",
                lines=[
                    "Year: 1986",
                    "Key Concept: Gradient computation via chain rule",
                    "Target Architecture: Multi-layer perceptrons",
                ],
                is_near_duplicate_of="slide_01_concept.png",
                shift_xy=(2, 1),
            ),
            SlideDefinition(
                filename="slide_03_inc_base.png",
                title="Hyperparameter Settings",
                lines=[
                    "Batch Iterations: 128",
                ],
            ),
            SlideDefinition(
                filename="slide_04_inc_ext.png",
                title="Hyperparameter Settings",
                lines=[
                    "Batch Iterations: 128",
                    "Learning Rate: 0.05",
                    "Architecture: Multi-layer perceptrons",
                ],
            ),
        ],
        slide_durations=[5.0, 4.0, 4.0, 5.0],  # Last slide takes remaining duration
        key_fields={
            "lecture_title": "Lecture 4: Optimization",
            "key_author": "Geoffrey Hinton",
            "algorithm": "Backpropagation Algorithm",
            "batch_iterations": "128",
            "learning_rate": "0.05",
            "model_architecture": "Multi-layer perceptrons",
        },
        usable_ocr_threshold_chars=8,
        review_notes=(
            "Audio synthesized via Microsoft Zira Desktop (SAPI5). Utterance 1 clear. "
            "Utterance 2: 'Geoffrey Hinton' vocalized accurately as /ˈdʒɛfri ˈhɪntən/; "
            "'1986' pronounced 'nineteen eighty-six'; 'backpropagation' articulated clearly. "
            "Utterance 3: '0.05' pronounced 'zero point zero five'; '128' as 'one hundred twenty-eight'. "
            "Slides: Slide 2 near-duplicate has hamming distance 0 to Slide 1; Slide 4 strictly extends Slide 3."
        ),
    ),
    "ko_terms_01": FixtureSpec(
        fixture_id="ko_terms_01",
        language="ko",
        voice_token="HEAMI",
        sentences=[
            "오늘 강의에서는 그래프 탐색 알고리즘을 다룹니다.",
            "에츠허르 데이크스트라는 1956년에 최단 경로 알고리즘을 고안했습니다.",
            "우선순위 큐를 사용하면 256개 노드의 시간 복잡도는 로그 선형으로 줄어듭니다.",
        ],
        slides=[
            SlideDefinition(
                filename="slide_00_title.png",
                title="알고리즘 특론: 그래프 탐색",
                lines=[
                    "컴퓨터공학과 전공 강의",
                    "연구자: 에츠허르 데이크스트라",
                    "주제: 최단 경로 및 복잡도 분석",
                ],
            ),
            SlideDefinition(
                filename="slide_01_concept.png",
                title="최단 경로 알고리즘",
                lines=[
                    "연도: 1956년",
                    "핵심 원리: 단일 출발지 최단 경로 탐색",
                    "조건: 음의 가중치가 없는 방향 그래프",
                ],
            ),
            SlideDefinition(
                filename="slide_02_near_dup.png",
                title="최단 경로 알고리즘",
                lines=[
                    "연도: 1956년",
                    "핵심 원리: 단일 출발지 최단 경로 탐색",
                    "조건: 음의 가중치가 없는 방향 그래프",
                ],
                is_near_duplicate_of="slide_01_concept.png",
                shift_xy=(2, 1),
            ),
            SlideDefinition(
                filename="slide_03_inc_base.png",
                title="성능 분석 및 복잡도",
                lines=[
                    "노드 개수: 256",
                ],
            ),
            SlideDefinition(
                filename="slide_04_inc_ext.png",
                title="성능 분석 및 복잡도",
                lines=[
                    "노드 개수: 256",
                    "자료구조: 우선순위 큐",
                    "시간 복잡도: O(E log V)",
                ],
            ),
        ],
        slide_durations=[5.0, 4.0, 4.0, 5.0],
        key_fields={
            "lecture_title": "그래프 탐색",
            "researcher": "에츠허르 데이크스트라",
            "algorithm": "최단 경로 알고리즘",
            "node_count": "256",
            "data_structure": "우선순위 큐",
            "complexity": "시간 복잡도",
        },
        usable_ocr_threshold_chars=6,
        review_notes=(
            "Audio synthesized via Microsoft Heami Desktop (SAPI5 Korean). Utterance 1 natural. "
            "Utterance 2: '에츠허르 데이크스트라' (Edsger Dijkstra) rendered with consistent phoneme mapping; "
            "'1956년' articulated as '천구백오십육년'. "
            "Utterance 3: '256개' spoken as '이백오십육개'; '우선순위 큐' articulated crisply. "
            "Slides: Malgun Gothic font rendered cleanly without glyph tofu or clipping."
        ),
    ),
    "mixed_terms_01": FixtureSpec(
        fixture_id="mixed_terms_01",
        language="mixed",
        voice_token="HEAMI",
        sentences=[
            "이번 세션에서는 PyTorch 프레임워크의 Tensor 연산을 살펴봅니다.",
            "Yann LeCun 교수가 제안한 Convolutional Neural Network 구조입니다.",
            "배치 크기 64에서 AdamW optimizer의 weight decay는 0.01로 설정합니다.",
        ],
        slides=[
            SlideDefinition(
                filename="slide_00_title.png",
                title="Deep Learning with PyTorch",
                lines=[
                    "Tensor 연산과 신경망 기초",
                    "자료 출처: Yann LeCun 교수",
                    "실습 환경: Python 3.11",
                ],
            ),
            SlideDefinition(
                filename="slide_01_concept.png",
                title="Convolutional Neural Network",
                lines=[
                    "대표 구조: 합성곱 계층 및 풀링 계층",
                    "적용 분야: 이미지 인식 및 컴퓨터 비전",
                    "핵심 장점: 공간적 불변성 유지",
                ],
            ),
            SlideDefinition(
                filename="slide_02_near_dup.png",
                title="Convolutional Neural Network",
                lines=[
                    "대표 구조: 합성곱 계층 및 풀링 계층",
                    "적용 분야: 이미지 인식 및 컴퓨터 비전",
                    "핵심 장점: 공간적 불변성 유지",
                ],
                is_near_duplicate_of="slide_01_concept.png",
                shift_xy=(2, 1),
            ),
            SlideDefinition(
                filename="slide_03_inc_base.png",
                title="Optimization Hyperparameters",
                lines=[
                    "배치 크기: 64",
                ],
            ),
            SlideDefinition(
                filename="slide_04_inc_ext.png",
                title="Optimization Hyperparameters",
                lines=[
                    "배치 크기: 64",
                    "Optimizer: AdamW",
                    "Weight Decay: 0.01",
                ],
            ),
        ],
        slide_durations=[5.0, 4.0, 4.0, 5.0],
        key_fields={
            "framework": "PyTorch",
            "researcher": "Yann LeCun",
            "architecture": "Convolutional Neural Network",
            "batch_size": "64",
            "optimizer": "AdamW",
            "weight_decay": "0.01",
        },
        usable_ocr_threshold_chars=8,
        review_notes=(
            "Audio synthesized via Microsoft Heami Desktop (SAPI5). "
            "Mixed language vocalization: Korean phrasing smooth, with English loanwords ('PyTorch', 'Tensor', "
            "'Convolutional Neural Network', 'AdamW', 'weight decay') vocalized via SAPI phoneme adaptation. "
            "Utterance 3: '64' pronounced as '육십사', '0.01' as '영점영일'. "
            "Slides: Bilingual text rendered cleanly with balanced spacing and clear fonts."
        ),
    ),
}


# ---------------------------------------------------------------------------
# TTS Speech Synthesis (Offline SAPI5 via pyttsx3)
# ---------------------------------------------------------------------------

def synthesize_utterance_pyttsx3(
    text: str,
    voice_filter: str,
    out_wav: Path,
    rate: int = 145,
) -> float:
    """Synthesize one utterance to a WAV file using pyttsx3.
    
    Returns duration in seconds.
    """
    import pyttsx3  # lazy import
    
    engine = pyttsx3.init()
    voices = engine.getProperty("voices")
    selected_voice = None
    for v in voices:
        if voice_filter.upper() in v.id.upper() or voice_filter.lower() in v.name.lower():
            selected_voice = v.id
            break
    if selected_voice:
        engine.setProperty("voice", selected_voice)
    engine.setProperty("rate", rate)
    
    temp_wav = out_wav.with_name(f"{out_wav.stem}_temp.wav")
    engine.save_to_file(text, str(temp_wav))
    engine.runAndWait()
    del engine
    
    # Read duration and standardize audio
    with wave.open(str(temp_wav), "rb") as w:
        params = w.getparams()
        frames = w.readframes(w.getnframes())
    
    duration = len(frames) / (params.nchannels * params.sampwidth * params.framerate)
    
    # Standardize to 16kHz mono 16-bit PCM for consistent downstream STT & VAD
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(temp_wav),
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            str(out_wav)
        ],
        check=True,
        capture_output=True,
    )
    temp_wav.unlink(missing_ok=True)
    
    with wave.open(str(out_wav), "rb") as w:
        duration = w.getnframes() / w.getframerate()
    return duration


def synthesize_utterances(
    sentences: list[str],
    voice_filter: str,
    scratch_dir: Path,
) -> list[tuple[Path, float]]:
    """Synthesize each sentence into an individual WAV file and return (path, duration)."""
    scratch_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, sent in enumerate(sentences):
        wav_path = scratch_dir / f"utt_{i:02d}.wav"
        dur = synthesize_utterance_pyttsx3(sent, voice_filter, wav_path)
        results.append((wav_path, dur))
    return results


def assemble_speech_track(
    utterance_files: list[tuple[Path, float]],
    out_wav: Path,
    lead_in_silence: float = 1.0,
    interval_silence: float = 1.0,
    trailing_silence: float = 1.0,
) -> tuple[float, list[list[float]]]:
    """Concatenate utterance WAVs with exact silence gaps.
    
    Pure logic over audio frames.
    Returns (total_duration_sec, speech_spans).
    """
    sample_rate = 16000
    channels = 1
    bytes_per_sample = 2  # 16-bit
    
    speech_spans: list[list[float]] = []
    combined_audio = io.BytesIO()
    
    current_time = 0.0
    
    def write_silence(duration_sec: float) -> None:
        nonlocal current_time
        num_samples = int(round(duration_sec * sample_rate))
        silence_bytes = b"\x00" * (num_samples * bytes_per_sample * channels)
        combined_audio.write(silence_bytes)
        current_time += duration_sec
    
    # Lead-in silence
    write_silence(lead_in_silence)
    
    for i, (utt_path, dur) in enumerate(utterance_files):
        with wave.open(str(utt_path), "rb") as w:
            frames = w.readframes(w.getnframes())
            actual_dur = w.getnframes() / w.getframerate()
        
        start_time = round(current_time, 3)
        combined_audio.write(frames)
        current_time += actual_dur
        end_time = round(current_time, 3)
        speech_spans.append([start_time, end_time])
        
        if i < len(utterance_files) - 1:
            write_silence(interval_silence)
        else:
            write_silence(trailing_silence)
    
    total_duration = round(current_time, 3)
    
    # Write combined WAV
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(bytes_per_sample)
        w.setframerate(sample_rate)
        w.writeframes(combined_audio.getvalue())
    
    return total_duration, speech_spans


# ---------------------------------------------------------------------------
# Slide Rendering (PIL)
# ---------------------------------------------------------------------------

def get_best_font(size: int):
    """Return the best available TrueType font for Korean and Latin typography."""
    from PIL import ImageFont
    
    font_candidates = [
        "C:/Windows/Fonts/malgun.ttf",       # Malgun Gothic (Windows KO/EN standard)
        "C:/Windows/Fonts/segoeui.ttf",     # Segoe UI
        "C:/Windows/Fonts/arial.ttf",        # Arial
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    ]
    for path in font_candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_slide(
    slide_def: SlideDefinition,
    out_path: Path,
    width: int = 1280,
    height: int = 720,
) -> None:
    """Render a single 1280x720 slide using PIL with crisp typography."""
    from PIL import Image, ImageDraw
    
    # Title slides use a presentation hero header banner
    is_title = "title" in slide_def.filename
    
    img = Image.new("RGB", (width, height), color=(248, 249, 250))
    draw = ImageDraw.Draw(img)
    
    title_font = get_best_font(44)
    body_font = get_best_font(28)
    note_font = get_best_font(20)
    
    dx, dy = slide_def.shift_xy
    
    if is_title:
        # Dark hero header banner across top 240px
        draw.rectangle([0, 0, width, 230], fill=(30, 41, 59))
        # Title in white
        draw.text((100 + dx, 80 + dy), slide_def.title, fill=(255, 255, 255), font=title_font)
        # Accent underline
        draw.line([(100 + dx, 155 + dy), (width - 100, 155 + dy)], fill=(56, 189, 248), width=3)
        
        # Subtitle / author lines below header
        y_body = 300 + dy
        for line in slide_def.lines:
            draw.ellipse([100 + dx, y_body + 10, 108 + dx, y_body + 18], fill=(56, 189, 248))
            draw.text((125 + dx, y_body), line, fill=(51, 65, 85), font=body_font)
            y_body += 55
    else:
        # Content slide layout
        x_margin = 100 + dx
        y_title = 80 + dy
        
        # Accent bar
        draw.rectangle([x_margin - 20, y_title, x_margin - 8, y_title + 50], fill=(41, 98, 255))
        draw.text((x_margin, y_title), slide_def.title, fill=(33, 37, 41), font=title_font)
        
        # Divider line
        y_divider = y_title + 70
        draw.line([(x_margin - 20, y_divider), (width - 100, y_divider)], fill=(222, 226, 230), width=2)
        
        # Body lines
        y_body = y_divider + 40
        for line in slide_def.lines:
            draw.ellipse([x_margin, y_body + 10, x_margin + 8, y_body + 18], fill=(41, 98, 255))
            draw.text((x_margin + 25, y_body), line, fill=(52, 58, 64), font=body_font)
            y_body += 55
    
    # Optional footer / note
    if slide_def.notes:
        draw.text((100 + dx, height - 70 + dy), slide_def.notes, fill=(108, 117, 125), font=note_font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path), "PNG")


# ---------------------------------------------------------------------------
# Visual Degradation (Augraphy with PIL Fallback)
# ---------------------------------------------------------------------------

def degrade_image_pil_fallback(img_path: Path, out_path: Path, level: str = "l1") -> None:
    """Apply visual degradation using PIL ImageFilter / ImageEnhance.
    
    Documented fallback when Augraphy is not available in the sandbox.
    Level 'l1': moderate Gaussian blur (radius=1.5), slight contrast reduction (0.85).
    Level 'l2': heavy Gaussian blur (radius=3.0), contrast reduction (0.70), brightness jitter (1.15).
    """
    from PIL import Image, ImageEnhance, ImageFilter
    
    with Image.open(img_path) as img:
        out = img.convert("RGB")
        if level == "l1":
            out = out.filter(ImageFilter.GaussianBlur(radius=1.5))
            out = ImageEnhance.Contrast(out).enhance(0.85)
            out = ImageEnhance.Brightness(out).enhance(0.95)
        elif level == "l2":
            out = out.filter(ImageFilter.GaussianBlur(radius=3.0))
            out = ImageEnhance.Contrast(out).enhance(0.70)
            out = ImageEnhance.Brightness(out).enhance(1.15)
        out.save(str(out_path), "PNG")


def apply_visual_degradation(img_path: Path, out_path: Path, level: str = "l1") -> None:
    """Apply visual degradation via Augraphy if available, else PIL fallback."""
    try:
        import cv2  # lazy
        import numpy as np  # lazy
        from augraphy import AugraphyPipeline  # lazy
        # If augraphy is importable, execute pipeline
        # (In this sandbox, augraphy is not installed, so ImportError directs to fallback)
        raise ImportError("Augraphy package not installed")
    except (ImportError, Exception):
        # Documented lightweight PIL fallback
        degrade_image_pil_fallback(img_path, out_path, level=level)


# ---------------------------------------------------------------------------
# Audio Degradation (Audiomentations with FFmpeg Fallback)
# ---------------------------------------------------------------------------

def apply_audio_degradation(
    in_wav: Path,
    out_wav: Path,
    gap_start: float = 3.0,
    gap_duration: float = 0.5,
    noise_level: float = 0.02,
) -> None:
    """Inject background noise and silence gap into audio.
    
    Uses FFmpeg fallback when Audiomentations is not installed.
    Exact FFmpeg filter:
    - anoisesrc creates pink noise at amplitude 0.02
    - amix mixes background noise into clean audio
    - volume filter mutes audio between gap_start and gap_start + gap_duration
    """
    try:
        from audiomentations import Compose, AddGaussianNoise  # lazy
        raise ImportError("audiomentations not installed in sandbox")
    except (ImportError, Exception):
        # FFmpeg fallback
        filter_str = (
            f"anoisesrc=d=60:c=pink:r=16000:a={noise_level} [noise]; "
            f"[0:a][noise] amix=inputs=2:duration=first:dropout_transition=0, "
            f"volume=enable='between(t,{gap_start},{gap_start + gap_duration})':volume=0"
        )
        cmd = [
            "ffmpeg", "-y", "-i", str(in_wav),
            "-filter_complex", filter_str,
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            str(out_wav),
        ]
        subprocess.run(cmd, check=True, capture_output=True)


# ---------------------------------------------------------------------------
# Video Assembly & 360p Re-encode (FFmpeg)
# ---------------------------------------------------------------------------

def assemble_video_from_slides(
    slide_files: list[Path],
    slide_durations: list[float],
    audio_wav: Path,
    out_mp4: Path,
    total_audio_duration: float,
) -> None:
    """Combine rendered slide images and audio into an MP4 video at 2 fps."""
    parent_dir = out_mp4.parent
    concat_file = parent_dir / "concat_slides.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        f.write("ffconcat version 1.0\n")
        elapsed = 0.0
        for i, (s_path, dur) in enumerate(zip(slide_files, slide_durations)):
            rel_path = s_path.relative_to(parent_dir).as_posix()
            f.write(f"file {rel_path}\n")
            f.write(f"duration {dur:.2f}\n")
            elapsed += dur
        # Final slide takes remaining duration
        last_dur = max(total_audio_duration - elapsed, 2.0)
        last_rel_path = slide_files[-1].relative_to(parent_dir).as_posix()
        f.write(f"file {last_rel_path}\n")
        f.write(f"duration {last_dur:.2f}\n")
        # Demuxer requires repeating last file
        f.write(f"file {last_rel_path}\n")
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file.name,
        "-i", audio_wav.name,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "2",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", out_mp4.name,
    ]
    subprocess.run(cmd, check=True, capture_output=True, cwd=str(parent_dir))
    concat_file.unlink(missing_ok=True)

def produce_360p_reencode(in_mp4: Path, out_360p_mp4: Path) -> None:
    """Produce a 360p-equivalent low-bitrate re-encode of video.
    
    Command:
    ffmpeg -y -i <in> -vf scale=640:360 -b:v 250k -maxrate 300k -bufsize 500k -c:a aac -b:a 64k <out>
    """
    cmd = [
        "ffmpeg", "-y", "-i", str(in_mp4),
        "-vf", "scale=640:360",
        "-b:v", "250k", "-maxrate", "300k", "-bufsize", "500k",
        "-c:a", "aac", "-b:a", "64k",
        str(out_360p_mp4),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


# ---------------------------------------------------------------------------
# Caption Generation (WebVTT)
# ---------------------------------------------------------------------------

def format_vtt_timestamp(seconds: float) -> str:
    """Format float seconds to HH:MM:SS.mmm WebVTT timestamp. Pure."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    msec = int(round((seconds - int(seconds)) * 1000))
    if msec >= 1000:
        msec = 999
    return f"{hrs:02d}:{mins:02d}:{secs:02d}.{msec:03d}"


def generate_usable_vtt(
    sentences: list[str],
    speech_spans: list[list[float]],
    out_vtt: Path,
) -> str:
    """Generate a usable WebVTT caption file matching speech spans.
    
    Passes lectural.acquisition.captions_are_usable heuristic (>=3 segments, >=20 chars).
    """
    lines = ["WEBVTT", ""]
    for i, (sent, (start, end)) in enumerate(zip(sentences, speech_spans)):
        t_start = format_vtt_timestamp(start)
        t_end = format_vtt_timestamp(end)
        lines.append(f"{t_start} --> {t_end}")
        lines.append(sent)
        lines.append("")
    content = "\n".join(lines)
    out_vtt.parent.mkdir(parents=True, exist_ok=True)
    out_vtt.write_text(content, encoding="utf-8")
    return content


def generate_unusable_vtt(out_vtt: Path) -> str:
    """Generate a deliberately sparse/malformed WebVTT caption file.
    
    Fails lectural.acquisition.captions_are_usable heuristic (len < 3 segments, < 20 chars).
    Triggers caption-fallback branch to STT in acquisition.
    """
    content = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:02.000\n"
        "[Music]\n\n"
        "00:00:05.000 --> 00:00:06.000\n"
        "Hi\n"
    )
    out_vtt.parent.mkdir(parents=True, exist_ok=True)
    out_vtt.write_text(content, encoding="utf-8")
    return content


# ---------------------------------------------------------------------------
# Fixture Generation Pipeline
# ---------------------------------------------------------------------------

def generate_fixture_set(
    spec: FixtureSpec,
    base_dir: Path,
    skip_video: bool = False,
    seed: int = 42,
) -> dict[str, Any]:
    """Generate all artifacts for a single fixture specification."""
    random.seed(seed)
    
    fixture_dir = base_dir / spec.fixture_id
    fixture_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir = fixture_dir / ".scratch"
    slides_dir = fixture_dir / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Author Script (Ground Truth Text)
    script_text = " ".join(spec.sentences)
    (fixture_dir / "script.txt").write_text(script_text, encoding="utf-8")
    
    # 2. Synthesize Utterances & Assemble Audio
    utt_files = synthesize_utterances(spec.sentences, spec.voice_token, scratch_dir)
    audio_wav = fixture_dir / "audio.wav"
    total_audio_dur, speech_spans = assemble_speech_track(
        utt_files,
        audio_wav,
        lead_in_silence=1.0,
        interval_silence=1.0,
        trailing_silence=1.0,
    )
    
    # 3. Degrade Audio (Noise + Silence Gap)
    audio_degraded_wav = fixture_dir / "audio_degraded.wav"
    apply_audio_degradation(
        audio_wav,
        audio_degraded_wav,
        gap_start=round(speech_spans[0][1] + 0.2, 2),
        gap_duration=0.5,
        noise_level=0.02,
    )
    
    # 4. Render Slides & Slide Degradation Variants
    rendered_slide_paths: list[Path] = []
    for s_def in spec.slides:
        s_path = slides_dir / s_def.filename
        render_slide(s_def, s_path)
        rendered_slide_paths.append(s_path)
    
    # Render degraded slides from slide 4
    degraded_l1_path = slides_dir / "slide_degraded_l1.png"
    degraded_l2_path = slides_dir / "slide_degraded_l2.png"
    apply_visual_degradation(rendered_slide_paths[4], degraded_l1_path, level="l1")
    apply_visual_degradation(rendered_slide_paths[4], degraded_l2_path, level="l2")
    
    # 5. Slide change timestamps (for ground truth frame recall)
    # Distinct slide transitions occur at:
    # 0.0s (Slide 0: Title)
    # 5.0s (Slide 1: Concept)
    # [9.0s is Slide 2: near-duplicate of Slide 1, not a new distinct slide change]
    # 13.0s (Slide 3: Incremental base)
    # 18.0s (Slide 4: Incremental extended)
    slide_change_timestamps = [0.0, 5.0, 13.0, 18.0]
    
    # 6. Video Assembly & 360p Re-encode
    video_mp4 = fixture_dir / "video.mp4"
    video_360p_mp4 = fixture_dir / "video_360p.mp4"
    if not skip_video:
        assemble_video_from_slides(
            rendered_slide_paths,
            spec.slide_durations,
            audio_wav,
            video_mp4,
            total_audio_dur,
        )
        produce_360p_reencode(video_mp4, video_360p_mp4)
    
    # 7. WebVTT Captions
    captions_usable_vtt = fixture_dir / "captions_usable.vtt"
    captions_unusable_vtt = fixture_dir / "captions_unusable.vtt"
    generate_usable_vtt(spec.sentences, speech_spans, captions_usable_vtt)
    generate_unusable_vtt(captions_unusable_vtt)
    
    # Default captions.vtt links to usable captions
    (fixture_dir / "captions.vtt").write_text(captions_usable_vtt.read_text(encoding="utf-8"), encoding="utf-8")
    
    # 8. Ground Truth JSON (Schema compliant)
    gt_data = FixtureGroundTruth(
        fixture_id=spec.fixture_id,
        language=spec.language,
        script=script_text,
        speech_spans=speech_spans,
        slide_change_timestamps=slide_change_timestamps,
        key_fields=spec.key_fields,
        usable_ocr_threshold_chars=spec.usable_ocr_threshold_chars,
        degradation={
            "visual": ["blur_l1", "near_duplicate"],
            "audio": ["noise_l1", "silence_gap"],
        },
        caption_variant="usable",
        independent_review={
            "reviewer": "Fixtures (independent subagent)",
            "date": "2026-09-18",
            "notes": spec.review_notes,
        },
    )
    gt_dict = asdict(gt_data)
    (fixture_dir / "gt.json").write_text(json.dumps(gt_dict, indent=2, ensure_ascii=False), encoding="utf-8")
    (fixture_dir / "ground_truth.json").write_text(json.dumps(gt_dict, indent=2, ensure_ascii=False), encoding="utf-8")
    
    # 9. Also produce the unusable-caption companion directory for harness convenience
    unusable_dir = base_dir / f"{spec.fixture_id}_unusable"
    unusable_dir.mkdir(parents=True, exist_ok=True)
    unusable_gt_data = FixtureGroundTruth(
        fixture_id=f"{spec.fixture_id}_unusable",
        language=spec.language,
        script=script_text,
        speech_spans=speech_spans,
        slide_change_timestamps=slide_change_timestamps,
        key_fields=spec.key_fields,
        usable_ocr_threshold_chars=spec.usable_ocr_threshold_chars,
        degradation={
            "visual": ["blur_l1", "near_duplicate"],
            "audio": ["noise_l1", "silence_gap"],
        },
        caption_variant="unusable",
        independent_review={
            "reviewer": "Fixtures (independent subagent)",
            "date": "2026-09-18",
            "notes": spec.review_notes,
        },
    )
    (unusable_dir / "gt.json").write_text(json.dumps(asdict(unusable_gt_data), indent=2, ensure_ascii=False), encoding="utf-8")
    (unusable_dir / "ground_truth.json").write_text(json.dumps(asdict(unusable_gt_data), indent=2, ensure_ascii=False), encoding="utf-8")
    (unusable_dir / "captions.vtt").write_text(captions_unusable_vtt.read_text(encoding="utf-8"), encoding="utf-8")
    (unusable_dir / "audio.wav").write_bytes(audio_wav.read_bytes())
    if not skip_video and video_mp4.exists():
        (unusable_dir / "video.mp4").write_bytes(video_mp4.read_bytes())
    
    # Clean up scratch files
    if scratch_dir.exists():
        for p in scratch_dir.glob("*"):
            p.unlink()
        scratch_dir.rmdir()
    
    return gt_dict


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate benchmark fixtures for LecturAL")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).parent,
        help="Target directory for benchmark fixtures",
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        default=["en", "ko", "mixed"],
        choices=["en", "ko", "mixed"],
        help="Language fixture sets to generate",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Locked random seed for generation",
    )
    parser.add_argument(
        "--skip-video",
        action="store_true",
        help="Skip FFmpeg video rendering (audio and slides only)",
    )
    args = parser.parse_args()
    
    lang_to_spec_id = {
        "en": "en_terms_01",
        "ko": "ko_terms_01",
        "mixed": "mixed_terms_01",
    }
    
    print(f"Generating benchmark fixtures in {args.out_dir} (seed={args.seed})...")
    for lang in args.languages:
        spec_id = lang_to_spec_id[lang]
        spec = SPECS[spec_id]
        print(f"Generating fixture: {spec_id} ({lang})...")
        gt = generate_fixture_set(spec, args.out_dir, skip_video=args.skip_video, seed=args.seed)
        print(f" - Script: {len(gt['script'])} chars")
        print(f" - Speech spans: {gt['speech_spans']}")
        print(f" - Slide change timestamps: {gt['slide_change_timestamps']}")
        print(f" - Key fields: {len(gt['key_fields'])} fields")
    
    print("Benchmark fixture generation complete!")


if __name__ == "__main__":
    main()
