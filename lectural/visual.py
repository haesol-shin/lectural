"""Visual track: extract keyframes and dedupe near-identical slides.

ffmpeg extracts candidate frames (I-frames + scene changes, downsampled);
perceptual hashes select stable slide changes. Legacy histogram/SSIM helpers
remain pure and unit-testable, but production dedupe routes through pHash so
small render noise collapses while real slide changes survive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
import shutil
from pathlib import Path

from .config import DEDUP_HIST_THRESHOLD, DEDUP_SSIM_THRESHOLD, SAMPLE_FPS


PHASH_HAMMING_THRESHOLD = 12
PHASH_CHANGE_PERSISTENCE = 2
_FRAME_TIMESTAMP_RE = re.compile(
    r"(?:^|[_-])(?P<value>\d+(?:\.\d+)?)(?P<unit>sec|s)?$",
    re.IGNORECASE,
)


@dataclass
class Frame:
    timestamp: float
    image_path: str
    ocr_text: str = ""
    is_slide: bool = False
    meta: dict = field(default_factory=dict)


def is_same_slide(
    hist_corr: float,
    ssim: float,
    hist_thr: float = DEDUP_HIST_THRESHOLD,
    ssim_thr: float = DEDUP_SSIM_THRESHOLD,
) -> bool:
    """Pure: two frames are the same slide when BOTH metrics clear threshold."""
    return hist_corr >= hist_thr and ssim >= ssim_thr


def _hash_to_int(hash_value: int | str | bytes) -> int:
    """Normalize supported hash representations to an integer."""
    if isinstance(hash_value, int):
        return hash_value
    if isinstance(hash_value, bytes):
        return int.from_bytes(hash_value, byteorder="big", signed=False)

    text = str(hash_value).strip().lower().replace("_", "")
    if not text:
        return 0
    if text.startswith(("0x", "0b")):
        return int(text, 0)
    base = 16 if any(ch in "abcdef" for ch in text) or len(text) > 10 else 10
    return int(text, base)


def phash_hamming_distance(hash_a: int | str | bytes, hash_b: int | str | bytes) -> int:
    """Pure Hamming distance between two perceptual hashes."""
    return (_hash_to_int(hash_a) ^ _hash_to_int(hash_b)).bit_count()


def is_same_phash(
    hash_a: int | str | bytes,
    hash_b: int | str | bytes,
    threshold: int = PHASH_HAMMING_THRESHOLD,
) -> bool:
    """Two pHashes represent the same slide when distance is within threshold."""
    return phash_hamming_distance(hash_a, hash_b) <= threshold


def select_phash_keyframe_indices(
    hashes: list[int | str | bytes],
    threshold: int = PHASH_HAMMING_THRESHOLD,
    persistence: int = PHASH_CHANGE_PERSISTENCE,
) -> list[int]:
    """Pure pHash selection with a consecutive-frame persistence gate.

    Frame 0 is kept. A frame whose hash is farther than `threshold` from the
    current kept slide starts a candidate change; the candidate's first frame is
    emitted only after `persistence` consecutive sampled frames match that
    candidate. One-off visual noise therefore does not create a slide.
    """
    if not hashes:
        return []

    required = max(int(persistence), 1)
    kept = [0]
    current_hash = hashes[0]
    candidate_idx: int | None = None
    candidate_hash: int | str | bytes | None = None
    candidate_count = 0

    for idx, hash_value in enumerate(hashes[1:], start=1):
        if is_same_phash(current_hash, hash_value, threshold):
            candidate_idx = None
            candidate_hash = None
            candidate_count = 0
            continue

        if candidate_hash is None or not is_same_phash(candidate_hash, hash_value, threshold):
            candidate_idx = idx
            candidate_hash = hash_value
            candidate_count = 1
        else:
            candidate_count += 1

        if candidate_count >= required:
            kept.append(candidate_idx if candidate_idx is not None else idx)
            current_hash = candidate_hash
            candidate_idx = None
            candidate_hash = None
            candidate_count = 0

    return kept


def parse_frame_timestamp_from_filename(
    image_path: str,
    fps: float = SAMPLE_FPS,
) -> tuple[float, str]:
    """Parse frame timestamp seconds from an extracted frame filename.

    `ffmpeg -frame_pts 1` names files with packet PTS. With the current sampled
    image sequence, integer PTS values are interpreted against the sampling fps
    (for example `frame_00042.png` at 2 fps -> 21.0s). Decimal values or values
    suffixed with `s`/`sec` are already seconds. Unparseable names fall back to
    0.0 with an explicit source marker.
    """
    stem, _ext = os.path.splitext(os.path.basename(image_path))
    match = _FRAME_TIMESTAMP_RE.search(stem)
    if match is None:
        return (0.0, "fallback_unparseable")

    token = match.group("value")
    value = max(float(token), 0.0)
    if match.group("unit") or "." in token:
        return (value, "filename_seconds")

    if fps > 0:
        return (value / fps, "filename_pts_over_fps")
    return (value, "filename_pts_no_fps")


def cleanup_raw_frames(
    raw_frames: list[Frame],
    final_slide_frames: list[Frame],
    *,
    keep_frames: bool = False,
) -> dict:
    """Delete or archive raw sampled frames while keeping final slides linked.

    Default mode removes non-final raw images from ``frames/``. Keep mode moves
    non-final raw images into ``frames/raw/`` and copies final slide images there
    too, so ``frames/`` still contains the images referenced by outline links.
    """
    raw_paths = [os.path.abspath(frame.image_path) for frame in raw_frames]
    final_paths = {os.path.abspath(frame.image_path) for frame in final_slide_frames}
    archived: list[str] = []
    removed: list[str] = []
    kept_final: list[str] = []

    if not raw_paths:
        return {
            "archived": archived,
            "removed": removed,
            "kept_final": kept_final,
            "raw_dir": None,
        }

    frames_dir = os.path.dirname(raw_paths[0])
    raw_dir = os.path.join(frames_dir, "raw")

    for source in raw_paths:
        if source in final_paths:
            kept_final.append(source)
            continue
        if not os.path.isfile(source):
            continue
        if keep_frames:
            os.makedirs(raw_dir, exist_ok=True)
            dest = os.path.join(raw_dir, os.path.basename(source))
            if os.path.abspath(dest) != source:
                if os.path.exists(dest):
                    os.remove(dest)
                shutil.move(source, dest)
                archived.append(dest)
        else:
            os.remove(source)
            removed.append(source)

    if not keep_frames and os.path.isdir(raw_dir):
        shutil.rmtree(raw_dir)

    if keep_frames:
        os.makedirs(raw_dir, exist_ok=True)
        for source in raw_paths:
            if source not in final_paths or not os.path.isfile(source):
                continue
            dest = os.path.join(raw_dir, os.path.basename(source))
            if os.path.abspath(dest) == source:
                continue
            shutil.copy2(source, dest)
            archived.append(dest)

    return {
        "archived": archived,
        "removed": removed,
        "kept_final": kept_final,
        "raw_dir": raw_dir if keep_frames else None,
    }


def select_keyframe_indices(
    consecutive_metrics: list[tuple[float, float]],
    hist_thr: float = DEDUP_HIST_THRESHOLD,
    ssim_thr: float = DEDUP_SSIM_THRESHOLD,
) -> list[int]:
    """Pure dedup over consecutive (hist_corr, ssim) pairs.

    `consecutive_metrics[i]` compares frame (i+1) against frame i. Frame 0 is
    always kept; frame (i+1) is kept only when it differs from frame i.
    Returns the sorted indices of kept frames.
    """
    kept = [0]
    for i, (hc, ss) in enumerate(consecutive_metrics):
        if not is_same_slide(hc, ss, hist_thr, ssim_thr):
            kept.append(i + 1)
    return kept


# --- ffmpeg / OpenCV backed extraction (lazy) ------------------------------

def extract_candidate_frames(video_path: str, out_dir: str, fps: float = SAMPLE_FPS) -> list[Frame]:
    """Extract downsampled + scene-change frames with ffmpeg. Lazy/subprocess."""
    import subprocess

    from .deps import require_binary

    require_binary("ffmpeg")
    os.makedirs(out_dir, exist_ok=True)
    pattern = os.path.join(out_dir, "frame_%05d.png")
    # Keep scene-change frames OR a steady low-fps sample, whichever fires.
    vf = f"select='gt(scene,0.3)+eq(pict_type,I)',fps={fps}"
    subprocess.run(
        ["ffmpeg", "-i", video_path, "-vf", vf, "-vsync", "vfr",
         "-frame_pts", "1", pattern],
        check=True,
    )
    frames: list[Frame] = []
    for name in sorted(os.listdir(out_dir)):
        if name.startswith("frame_") and name.endswith(".png"):
            path = os.path.join(out_dir, name)
            timestamp, source = parse_frame_timestamp_from_filename(path, fps)
            frames.append(
                Frame(
                    timestamp=timestamp,
                    image_path=path,
                    meta={"timestamp_source": source, "sample_fps": fps},
                )
            )
    return frames

def _cv2_imread_unicode(image_path: str, flags: int, cv2, np):
    """Read an image through OpenCV without cv2.imread path encoding limits."""
    try:
        data = Path(image_path).read_bytes()
    except OSError:
        return None
    if not data:
        return None
    buf = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(buf, flags)


def _pair_metrics(path_a: str, path_b: str) -> tuple[float, float]:
    """(hist_corr, ssim) between two image files. Lazy OpenCV/numpy."""
    import cv2  # lazy
    import numpy as np  # lazy

    a = _cv2_imread_unicode(path_a, cv2.IMREAD_COLOR, cv2, np)
    b = _cv2_imread_unicode(path_b, cv2.IMREAD_COLOR, cv2, np)
    if a is None or b is None:
        return (0.0, 0.0)
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))

    ha = cv2.calcHist([a], [0, 1, 2], None, [8, 8, 8], [0, 256] * 3)
    hb = cv2.calcHist([b], [0, 1, 2], None, [8, 8, 8], [0, 256] * 3)
    cv2.normalize(ha, ha)
    cv2.normalize(hb, hb)
    hist_corr = float(cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL))

    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float64)
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float64)
    ssim = _ssim(ga, gb, np)
    return (hist_corr, ssim)


def _ssim(a, b, np, win: int = 7) -> float:
    """Mean of windowed SSIM map between two grayscale arrays. Pure given numpy.

    Uses a `win`x`win` box filter to compute local statistics (spatially
    sensitive), unlike a single global window which is blind to layout changes
    that share global luminance stats. Returns the mean local SSIM.
    """
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2

    def box(x):
        # Separable box filter via cumulative sums; pure numpy, no scipy.
        k = win
        pad = k // 2
        xp = np.pad(x, pad, mode="edge")
        cs = np.cumsum(np.cumsum(xp, axis=0), axis=1)
        cs = np.pad(cs, ((1, 0), (1, 0)), mode="constant")
        h, w = x.shape
        s = (
            cs[k:k + h, k:k + w]
            - cs[0:h, k:k + w]
            - cs[k:k + h, 0:w]
            + cs[0:h, 0:w]
        )
        return s / (k * k)

    mu_a = box(a)
    mu_b = box(b)
    mu_a2, mu_b2, mu_ab = mu_a * mu_a, mu_b * mu_b, mu_a * mu_b
    va = box(a * a) - mu_a2
    vb = box(b * b) - mu_b2
    cov = box(a * b) - mu_ab
    num = (2 * mu_ab + c1) * (2 * cov + c2)
    den = (mu_a2 + mu_b2 + c1) * (va + vb + c2)
    smap = num / den
    return float(np.clip(smap.mean(), -1.0, 1.0))


def _phash_from_32x32(gray32, np) -> int:
    """Return a 64-bit DCT perceptual hash from a 32x32 grayscale array."""
    n = 32
    x = np.arange(n)
    k = np.arange(8)[:, None]
    basis = np.cos((np.pi / (2 * n)) * (2 * x + 1) * k)
    basis[0, :] *= np.sqrt(1 / n)
    basis[1:, :] *= np.sqrt(2 / n)
    coeffs = basis @ gray32.astype(np.float64) @ basis.T
    flat = coeffs.reshape(-1)
    median = float(np.median(flat[1:]))
    bits = flat > median

    value = 0
    for bit in bits:
        value = (value << 1) | int(bool(bit))
    return value


def _image_phash(image_path: str) -> int:
    """Compute a DCT pHash for an image path. Imports image backends lazily."""
    try:
        import cv2  # lazy
        import numpy as np  # lazy
    except ImportError:
        try:
            import numpy as np  # type: ignore[no-redef]  # lazy
            from PIL import Image  # lazy
        except ImportError as pil_error:
            raise RuntimeError(
                "Image pHash requires OpenCV or Pillow plus numpy"
            ) from pil_error

        with Image.open(image_path) as img:
            gray = img.convert("L")
            crop_h = max(1, int(round(gray.height * 0.60)))
            gray = gray.crop((0, 0, gray.width, crop_h)).resize((32, 32))
            return _phash_from_32x32(np.asarray(gray, dtype=np.float64), np)

    gray = _cv2_imread_unicode(image_path, cv2.IMREAD_GRAYSCALE, cv2, np)
    if gray is None:
        raise ValueError(f"Unable to read image for pHash: {image_path}")
    crop_h = max(1, int(round(gray.shape[0] * 0.60)))
    cropped = gray[:crop_h, :]
    resized = cv2.resize(cropped, (32, 32), interpolation=cv2.INTER_AREA)
    return _phash_from_32x32(resized, np)

def dedupe_frames(frames: list[Frame]) -> list[Frame]:
    """Compute perceptual hashes and keep stable distinct slides."""
    if len(frames) <= 1:
        return list(frames)

    hashes = [_image_phash(frame.image_path) for frame in frames]
    for i, (frame, hash_value) in enumerate(zip(frames, hashes)):
        frame.meta["phash"] = f"{hash_value:016x}"
        frame.meta["phash_hamming_threshold"] = PHASH_HAMMING_THRESHOLD
        if i > 0:
            frame.meta["phash_hamming_from_previous"] = phash_hamming_distance(
                hashes[i - 1],
                hash_value,
            )

    keep = set(select_phash_keyframe_indices(hashes))
    return [frame for i, frame in enumerate(frames) if i in keep]
