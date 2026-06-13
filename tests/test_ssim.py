"""Unit tests for the windowed SSIM approximation (visual dedup metric).

Requires numpy; skipped when numpy is not installed.
"""

import pytest

np = pytest.importorskip("numpy")

from lectural.visual import _ssim


def test_identical_images_ssim_is_one():
    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, size=(40, 60)).astype(np.float64)
    assert _ssim(img, img, np) == pytest.approx(1.0, abs=1e-6)


def test_layout_change_same_global_stats_scores_low():
    # Two images with the SAME global mean/variance but different spatial
    # layout: a global SSIM would be fooled; the windowed SSIM must not be.
    a = np.zeros((40, 40), dtype=np.float64)
    a[:, :20] = 255.0  # left half white
    b = np.zeros((40, 40), dtype=np.float64)
    b[:20, :] = 255.0  # top half white -> identical histogram, different layout
    assert a.mean() == pytest.approx(b.mean())
    assert _ssim(a, b, np) < 0.9  # spatially sensitive


def test_small_perturbation_scores_high():
    rng = np.random.default_rng(1)
    a = rng.integers(0, 256, size=(50, 50)).astype(np.float64)
    b = np.clip(a + rng.normal(0, 1.0, size=a.shape), 0, 255)
    assert _ssim(a, b, np) > 0.95


def test_ssim_is_bounded():
    rng = np.random.default_rng(2)
    a = rng.integers(0, 256, size=(30, 30)).astype(np.float64)
    b = rng.integers(0, 256, size=(30, 30)).astype(np.float64)
    s = _ssim(a, b, np)
    assert -1.0 <= s <= 1.0
