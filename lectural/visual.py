"""Visual track: extract keyframes and dedupe near-identical slides.

ffmpeg extracts candidate frames (I-frames + scene changes, downsampled);
OpenCV computes per-pair similarity. The *selection* logic is a pure function
over similarity metrics so over/under-dedup behaviour is unit-tested without
any binaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import DEDUP_HIST_THRESHOLD, DEDUP_SSIM_THRESHOLD, SAMPLE_FPS


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
    import os
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
            frames.append(Frame(timestamp=0.0, image_path=os.path.join(out_dir, name)))
    return frames


def _pair_metrics(path_a: str, path_b: str) -> tuple[float, float]:
    """(hist_corr, ssim) between two image files. Lazy OpenCV/numpy."""
    import cv2  # lazy
    import numpy as np  # lazy

    a = cv2.imread(path_a)
    b = cv2.imread(path_b)
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


def dedupe_frames(frames: list[Frame]) -> list[Frame]:
    """Compute consecutive metrics and keep distinct slides. Orchestration."""
    if len(frames) <= 1:
        return list(frames)
    metrics = [
        _pair_metrics(frames[i].image_path, frames[i + 1].image_path)
        for i in range(len(frames) - 1)
    ]
    keep = set(select_keyframe_indices(metrics))
    return [f for i, f in enumerate(frames) if i in keep]
